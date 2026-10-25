"""
pumpfun_api.py — data token pump.fun untuk scanner.

Token pump.fun yang masih di bonding curve sering BELUM di-index DexScreener,
sehingga scan berakhir "No results found". Modul ini mengambil datanya
langsung dari pump.fun dengan dua lapis sumber:

1. Frontend API pump.fun (frontend-api-v3.pump.fun/coins/{mint}) — data
   paling lengkap (nama, MC USD, ATH, sosial). API ini TIDAK resmi dan ada di
   belakang Cloudflare: dari IP server/VPS bisa saja dijawab 403.
2. Fallback on-chain: baca akun BondingCurve langsung lewat Solana RPC
   (layout dari IDL resmi github.com/pump-fun/pump-public-docs). Tetap jalan
   walau API pump.fun memblokir, tapi tanpa ATH/sosial.

Fungsi publik TIDAK pernah raise — kalau token bukan coin pump.fun atau semua
sumber gagal, hasilnya None, supaya handler Telegram tidak ikut crash.
"""
import asyncio
import base64
import hashlib
import logging
import os
import re
import struct
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import aiohttp

logger = logging.getLogger(__name__)

# ==========================
# Konstanta
# ==========================
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
METAPLEX_PROGRAM_ID = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
WSOL_MINT = "So11111111111111111111111111111111111111112"
DEFAULT_PUBKEY = "11111111111111111111111111111111"  # Pubkey::default()

FRONTEND_API_URL = "https://frontend-api-v3.pump.fun"
COINGECKO_SOL_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
PUBLIC_SOLANA_RPC = "https://api.mainnet-beta.solana.com"

PUMP_COIN_URL = "https://pump.fun/coin/{mint}"

TOKEN_DECIMALS = 6  # semua coin pump.fun memakai 6 desimal
LAMPORTS_PER_SOL = 1_000_000_000
STANDARD_TOTAL_SUPPLY = 1_000_000_000 * 10 ** TOKEN_DECIMALS  # 1B token (raw)
# Jumlah token yang dijual lewat bonding curve (Global.initial_real_token_reserves).
# Sisa 206.9M token disimpan untuk likuiditas saat coin graduate.
INITIAL_REAL_TOKEN_RESERVES = 793_100_000 * 10 ** TOKEN_DECIMALS

# Discriminator Anchor akun BondingCurve (dari IDL pump.json)
BONDING_CURVE_DISCRIMINATOR = bytes([23, 183, 248, 55, 96, 216, 172, 96])

# Header ala browser: frontend API melayani web pump.fun, request tanpa
# Origin/User-Agent browser lebih sering ditolak Cloudflare.
FRONTEND_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
}

# Timeout WAJIB di semua request — tanpa timeout satu API yang menggantung
# membuat handler scan ikut menggantung (bot terlihat mati). Batas total
# membatasi kasus terburuk saat beberapa sumber lambat berurutan.
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)
TOTAL_TIMEOUT = 25

# Cache singkat: satu scan memanggil data yang sama dua kali (report +
# simpan scan PnL). TTL pendek supaya tombol Refresh tetap dapat data baru.
_CACHE_TTL = 20.0
_CACHE_MAX = 256
_token_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

_SOL_PRICE_TTL = 60.0
_sol_price_cache: Tuple[float, float] = (0.0, 0.0)  # (monotonic ts, harga)

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_DOMAIN_RE = re.compile(r"^[\w-]+(\.[\w-]+)+(/|$)")


# ==========================
# Base58 & PDA (tanpa dependensi tambahan)
# ==========================
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + out


def b58decode(text: str) -> bytes:
    n = 0
    for ch in text:
        n = n * 58 + _B58_INDEX[ch]  # KeyError kalau karakter bukan base58
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(text) - len(text.lstrip("1"))
    return b"\0" * pad + body


def pubkey_bytes(address: str) -> Optional[bytes]:
    """32 byte public key dari alamat Solana, atau None kalau bukan alamat valid."""
    if not isinstance(address, str) or not _BASE58_RE.match(address):
        return None
    try:
        raw = b58decode(address)
    except KeyError:
        return None
    return raw if len(raw) == 32 else None


def is_solana_address(address: str) -> bool:
    return pubkey_bytes(address) is not None


# Kurva ed25519: p = 2^255 - 19, d = -121665/121666
_ED_P = 2 ** 255 - 19
_ED_D = (-121665 * pow(121666, _ED_P - 2, _ED_P)) % _ED_P


def _is_on_ed25519_curve(point: bytes) -> bool:
    """Sama dengan CompressedEdwardsY::decompress().is_some() di Solana:
    titik valid kalau x^2 = (y^2 - 1) / (d*y^2 + 1) punya akar kuadrat."""
    y = int.from_bytes(point, "little") & ((1 << 255) - 1)
    y2 = y * y % _ED_P
    u = (y2 - 1) % _ED_P
    v = (_ED_D * y2 + 1) % _ED_P
    x2 = u * pow(v, _ED_P - 2, _ED_P) % _ED_P
    return x2 == 0 or pow(x2, (_ED_P - 1) // 2, _ED_P) == 1


def find_program_address(seeds: List[bytes], program_id: bytes) -> Tuple[bytes, int]:
    """Port dari Pubkey::find_program_address (Solana)."""
    for bump in range(255, -1, -1):
        digest = hashlib.sha256(
            b"".join(seeds) + bytes([bump]) + program_id + b"ProgramDerivedAddress"
        ).digest()
        if not _is_on_ed25519_curve(digest):
            return digest, bump
    raise ValueError("Tidak ada bump seed yang valid")


def bonding_curve_address(mint: str) -> Optional[str]:
    mint_raw = pubkey_bytes(mint)
    if mint_raw is None:
        return None
    pda, _ = find_program_address([b"bonding-curve", mint_raw], b58decode(PUMP_PROGRAM_ID))
    return b58encode(pda)


def metaplex_metadata_address(mint: str) -> Optional[str]:
    mint_raw = pubkey_bytes(mint)
    if mint_raw is None:
        return None
    program = b58decode(METAPLEX_PROGRAM_ID)
    pda, _ = find_program_address([b"metadata", program, mint_raw], program)
    return b58encode(pda)


# ==========================
# Helper umum
# ==========================
def _num(value: Any) -> Optional[float]:
    """float dari angka/str angka; None untuk None, bool, atau teks rusak."""
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def _positive(value: Any) -> Optional[float]:
    n = _num(value)
    return n if n is not None and n > 0 else None


def _first_present(data: Dict[str, Any], *keys: str) -> Any:
    """Nilai key pertama yang ada — pump.fun mengganti nama field
    *_sol_reserves → *_quote_reserves, dukung dua-duanya."""
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def _to_seconds(value: Any) -> Optional[float]:
    """Timestamp pump.fun dalam milidetik; terima juga detik demi aman."""
    n = _num(value)
    if not n or n <= 0:
        return None
    return n / 1000 if n > 1e11 else n


def _is_sol_quote(quote_mint: Optional[str]) -> bool:
    # quote_mint = Pubkey::default() untuk semua coin yang dipasangkan dengan SOL
    return quote_mint in (None, "", DEFAULT_PUBKEY, WSOL_MINT)


def _safe_url(value: Any, handle_prefix: Optional[str] = None) -> Optional[str]:
    """
    Normalisasi link sosial dari data pump.fun (diisi bebas oleh creator).
    Hanya http(s); karakter yang merusak parse Markdown Telegram (spasi, `()`,
    backtick, `[]`) di-percent-encode, supaya satu link aneh tidak membuat
    Telegram menolak seluruh report ("Can't parse entities").
    """
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        if _DOMAIN_RE.match(url):
            url = "https://" + url
        elif handle_prefix:
            url = handle_prefix + url.lstrip("@/")
        else:
            return None
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    return quote(url, safe=":/?#@!$&'*+,;=%-._~")


def _bonding_progress(real_token_raw: Optional[float], total_supply_raw: Optional[float],
                      complete: bool, mayhem: bool) -> Optional[float]:
    """Persen bonding curve terisi (100% = graduate)."""
    if complete:
        return 100.0
    # Rumus hanya berlaku untuk coin standar 1B supply; mode lain (mis. Mayhem)
    # punya parameter berbeda → lebih baik N/A daripada angka salah.
    if real_token_raw is None or mayhem or total_supply_raw != STANDARD_TOTAL_SUPPLY:
        return None
    pct = (1 - real_token_raw / INITIAL_REAL_TOKEN_RESERVES) * 100
    return max(0.0, min(100.0, pct))


def _mc_sol_from_reserves(virtual_token_raw: Optional[float], virtual_sol_raw: Optional[float],
                          total_supply_raw: Optional[float], decimals: int) -> Optional[float]:
    """MC dalam SOL = harga bonding curve × total supply (rumus MC pump.fun)."""
    if not virtual_token_raw or not virtual_sol_raw or not total_supply_raw:
        return None
    price_sol = (virtual_sol_raw / LAMPORTS_PER_SOL) / (virtual_token_raw / 10 ** decimals)
    return price_sol * (total_supply_raw / 10 ** decimals)


def _host(url: str) -> str:
    # Log host saja: URL RPC bisa memuat API key (Helius ?api-key=...)
    return urlparse(url).netloc or "?"


def _redact(text: str) -> str:
    # Pesan error aiohttp (mis. InvalidURL) bisa memuat URL lengkap + API key
    return re.sub(r"(api[-_]?key=)[^&\s'\"]+", r"\1***", text, flags=re.IGNORECASE)


async def _request_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> Any:
    try:
        async with session.request(method, url, **kwargs) as resp:
            if resp.status != 200:
                logger.info(f"[pump.fun] {method.upper()} {_host(url)} -> HTTP {resp.status}")
                return None
            return await resp.json(content_type=None)
    except Exception as e:  # timeout, koneksi putus, body bukan JSON
        logger.warning(f"[pump.fun] {method.upper()} {_host(url)} gagal: {type(e).__name__}: {_redact(str(e))}")
        return None


def _rpc_url() -> str:
    url = (os.getenv("SOL_RPC") or "").strip()
    if url:
        return url
    helius_key = (os.getenv("HELIUS_API_KEY") or "").strip()
    if helius_key:
        return f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    return PUBLIC_SOLANA_RPC


async def get_sol_price_usd(session: aiohttp.ClientSession) -> Optional[float]:
    """Harga SOL/USD (cache 60 detik): CoinGecko, fallback ke pump.fun."""
    global _sol_price_cache
    ts, cached = _sol_price_cache
    if cached > 0 and time.monotonic() - ts < _SOL_PRICE_TTL:
        return cached

    price = None
    data = await _request_json(session, "get", COINGECKO_SOL_PRICE_URL)
    if isinstance(data, dict) and isinstance(data.get("solana"), dict):
        price = _num(data["solana"].get("usd"))
    if not price:
        data = await _request_json(session, "get", f"{FRONTEND_API_URL}/sol-price", headers=FRONTEND_HEADERS)
        if isinstance(data, dict):
            price = _num(data.get("solPrice"))

    if price and price > 0:
        _sol_price_cache = (time.monotonic(), price)
        return price
    return None


# ==========================
# Sumber 1: frontend API pump.fun
# ==========================
async def _fetch_from_frontend(session: aiohttp.ClientSession, mint: str) -> Optional[Dict[str, Any]]:
    coin = await _request_json(
        session, "get", f"{FRONTEND_API_URL}/coins/{mint}",
        params={"sync": "true"}, headers=FRONTEND_HEADERS,
    )
    # Validasi: API kadang membalas 200 dengan body error / coin lain
    if not isinstance(coin, dict) or coin.get("mint") != mint:
        return None

    decimals = TOKEN_DECIMALS
    total_raw = _num(coin.get("total_supply")) or STANDARD_TOTAL_SUPPLY
    supply = total_raw / 10 ** decimals
    complete = bool(coin.get("complete"))
    sol_quote = _is_sol_quote(coin.get("quote_mint"))

    mc_usd = _positive(coin.get("usd_market_cap"))
    mc_sol = _positive(coin.get("market_cap"))
    sol_usd = mc_usd / mc_sol if mc_usd and mc_sol else None

    # usd_market_cap kosong → hitung sendiri dari MC SOL / virtual reserves
    if not mc_usd and sol_quote:
        if not mc_sol and not complete:
            mc_sol = _mc_sol_from_reserves(
                _num(coin.get("virtual_token_reserves")),
                _num(_first_present(coin, "virtual_sol_reserves", "virtual_quote_reserves")),
                total_raw, decimals,
            )
        if mc_sol:
            sol_usd = await get_sol_price_usd(session)
            mc_usd = mc_sol * sol_usd if sol_usd else None

    liquidity = None
    real_sol = _num(_first_present(coin, "real_sol_reserves", "real_quote_reserves"))
    if not complete and sol_quote and real_sol is not None and sol_usd:
        liquidity = real_sol / LAMPORTS_PER_SOL * sol_usd

    return {
        "mint": mint,
        "name": coin.get("name") if isinstance(coin.get("name"), str) else None,
        "symbol": coin.get("symbol") if isinstance(coin.get("symbol"), str) else None,
        "source": "pump.fun API",
        "price_usd": mc_usd / supply if mc_usd and supply else None,
        "market_cap_usd": mc_usd,
        "liquidity_usd": liquidity,
        "complete": complete,
        "bonding_progress": _bonding_progress(
            _num(coin.get("real_token_reserves")), total_raw, complete,
            bool(coin.get("is_mayhem_mode")),
        ),
        "ath_market_cap_usd": _positive(coin.get("ath_market_cap")),
        "ath_timestamp": _to_seconds(coin.get("ath_market_cap_timestamp")),
        "created_timestamp": _to_seconds(coin.get("created_timestamp")),
        "creator": coin.get("creator") if is_solana_address(coin.get("creator")) else None,
        "twitter": _safe_url(coin.get("twitter"), "https://x.com/"),
        "telegram": _safe_url(coin.get("telegram"), "https://t.me/"),
        "website": _safe_url(coin.get("website")),
    }


# ==========================
# Sumber 2: on-chain (akun BondingCurve via Solana RPC)
# ==========================
def decode_bonding_curve(raw: Optional[bytes]) -> Optional[Dict[str, Any]]:
    """
    Decode akun BondingCurve (Borsh). Urutan field sesuai IDL:
      [0:8]   discriminator
      [8:48]  virtual_token_reserves, virtual_quote_reserves, real_token_reserves,
              real_quote_reserves, token_total_supply (u64 LE)
      [48]    complete (bool)
      [49:81] creator (pubkey)
      [81]    is_mayhem_mode   [82] is_cashback_coin
      [83:115] quote_mint (pubkey; default = SOL)
    Field yang ditambahkan belakangan bisa tidak ada di akun lama → default.
    """
    if not raw or len(raw) < 49 or raw[:8] != BONDING_CURVE_DISCRIMINATOR:
        return None
    vtok, vquote, rtok, rquote, supply = struct.unpack_from("<5Q", raw, 8)
    creator = raw[49:81] if len(raw) >= 81 else b""
    quote_mint = raw[83:115] if len(raw) >= 115 else b""
    return {
        "virtual_token_reserves": vtok,
        "virtual_quote_reserves": vquote,
        "real_token_reserves": rtok,
        "real_quote_reserves": rquote,
        "token_total_supply": supply,
        "complete": raw[48] != 0,
        "creator": b58encode(creator) if any(creator) else None,
        "is_mayhem_mode": len(raw) > 81 and raw[81] != 0,
        "quote_mint": b58encode(quote_mint) if any(quote_mint) else None,
    }


def _account_bytes(account: Any) -> Optional[bytes]:
    """Data akun dari RPC. Dengan encoding jsonParsed, akun yang tidak bisa
    di-parse (BondingCurve, metadata Metaplex) dikembalikan sebagai base64."""
    if not isinstance(account, dict):
        return None
    data = account.get("data")
    if isinstance(data, list) and len(data) == 2 and data[1] == "base64":
        data = data[0]
    if not isinstance(data, str):
        return None
    try:
        return base64.b64decode(data)
    except (ValueError, TypeError):
        return None


def _read_borsh_string(raw: bytes, offset: int) -> Tuple[Optional[str], int]:
    if offset + 4 > len(raw):
        return None, offset
    (length,) = struct.unpack_from("<I", raw, offset)
    start, end = offset + 4, offset + 4 + length
    if end > len(raw):
        return None, offset
    return raw[start:end].decode("utf-8", errors="replace").strip("\x00").strip(), end


def decode_metaplex_name_symbol(raw: Optional[bytes]) -> Tuple[Optional[str], Optional[str]]:
    # key(u8) + update_authority(32) + mint(32), lalu name & symbol (Borsh string)
    if not raw or len(raw) < 65:
        return None, None
    name, offset = _read_borsh_string(raw, 65)
    symbol, _ = _read_borsh_string(raw, offset) if name is not None else (None, offset)
    return name or None, symbol or None


async def _fetch_from_chain(session: aiohttp.ClientSession, mint: str) -> Optional[Dict[str, Any]]:
    curve_addr = bonding_curve_address(mint)
    metadata_addr = metaplex_metadata_address(mint)
    if not curve_addr or not metadata_addr:
        return None

    # Satu panggilan RPC untuk 3 akun: bonding curve, mint, metadata Metaplex
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
        "params": [[curve_addr, mint, metadata_addr], {"encoding": "jsonParsed", "commitment": "confirmed"}],
    }
    data = await _request_json(session, "post", _rpc_url(), json=payload)
    result = data.get("result") if isinstance(data, dict) else None
    accounts = result.get("value") if isinstance(result, dict) else None
    if not isinstance(accounts, list) or len(accounts) != 3:
        return None
    curve_acc, mint_acc, metadata_acc = accounts

    if not isinstance(curve_acc, dict) or curve_acc.get("owner") != PUMP_PROGRAM_ID:
        return None  # bukan coin pump.fun
    curve = decode_bonding_curve(_account_bytes(curve_acc))
    if not curve:
        return None

    # Mint: decimals + metadata Token-2022 (coin create_v2) dari jsonParsed
    decimals = TOKEN_DECIMALS
    name = symbol = None
    mint_data = mint_acc.get("data") if isinstance(mint_acc, dict) else None
    parsed = mint_data.get("parsed") if isinstance(mint_data, dict) else None
    info = parsed.get("info") if isinstance(parsed, dict) else None
    if isinstance(info, dict):
        if isinstance(info.get("decimals"), int):
            decimals = info["decimals"]
        for ext in info.get("extensions") or []:
            if isinstance(ext, dict) and ext.get("extension") == "tokenMetadata" and isinstance(ext.get("state"), dict):
                name = ext["state"].get("name") or None
                symbol = ext["state"].get("symbol") or None

    # Coin SPL lama: name/symbol ada di akun metadata Metaplex
    if (not name or not symbol) and isinstance(metadata_acc, dict) and metadata_acc.get("owner") == METAPLEX_PROGRAM_ID:
        meta_name, meta_symbol = decode_metaplex_name_symbol(_account_bytes(metadata_acc))
        name = name or meta_name
        symbol = symbol or meta_symbol

    complete = curve["complete"]
    total_raw = float(curve["token_total_supply"]) or None
    mc_usd = liquidity = None
    # Setelah graduate, reserve curve sudah beku (trading pindah ke AMM) →
    # harga dari curve basi; lebih baik N/A daripada angka salah. Quote selain
    # SOL juga dilewati karena harga quote-nya tidak diketahui.
    if not complete and _is_sol_quote(curve["quote_mint"]):
        mc_sol = _mc_sol_from_reserves(
            curve["virtual_token_reserves"], curve["virtual_quote_reserves"], total_raw, decimals,
        )
        sol_usd = await get_sol_price_usd(session) if mc_sol else None
        if sol_usd:
            mc_usd = mc_sol * sol_usd
            liquidity = curve["real_quote_reserves"] / LAMPORTS_PER_SOL * sol_usd
    supply = total_raw / 10 ** decimals if total_raw else None

    return {
        "mint": mint,
        "name": name,
        "symbol": symbol,
        "source": "on-chain bonding curve",
        "price_usd": mc_usd / supply if mc_usd and supply else None,
        "market_cap_usd": mc_usd,
        "liquidity_usd": liquidity,
        "complete": complete,
        "bonding_progress": _bonding_progress(
            curve["real_token_reserves"], total_raw, complete, curve["is_mayhem_mode"],
        ),
        "ath_market_cap_usd": None,
        "ath_timestamp": None,
        "created_timestamp": None,
        "creator": curve["creator"],
        "twitter": None,
        "telegram": None,
        "website": None,
    }


# ==========================
# API publik
# ==========================
async def get_pumpfun_token(mint: str) -> Optional[Dict[str, Any]]:
    """
    Data token pump.fun (dict ternormalisasi) atau None kalau `mint` bukan
    coin pump.fun / semua sumber gagal. Nilai yang tidak diketahui = None.
    """
    mint = (mint or "").strip()
    if not is_solana_address(mint):
        return None

    now = time.monotonic()
    cached = _token_cache.get(mint)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    async def _fetch() -> Optional[Dict[str, Any]]:
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            found = await _fetch_from_frontend(session, mint)
            if found is None:
                found = await _fetch_from_chain(session, mint)
            return found

    try:
        token = await asyncio.wait_for(_fetch(), timeout=TOTAL_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"[pump.fun] Timeout {TOTAL_TIMEOUT}s mengambil data {mint}")
        return None
    except Exception as e:
        logger.error(f"[pump.fun] Gagal mengambil data {mint}: {e}", exc_info=True)
        return None

    if token:
        if len(_token_cache) >= _CACHE_MAX:
            for key in [k for k, (ts, _) in _token_cache.items() if now - ts >= _CACHE_TTL]:
                del _token_cache[key]
            if len(_token_cache) >= _CACHE_MAX:
                _token_cache.clear()
        _token_cache[mint] = (now, token)
        logger.info(f"[pump.fun] {mint} ditemukan via {token['source']}")
    return token


def pumpfun_coin_url(mint: str) -> str:
    return PUMP_COIN_URL.format(mint=mint)
