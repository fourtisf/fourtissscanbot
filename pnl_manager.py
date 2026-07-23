import os
import sqlite3
import asyncio
import re
import random
from contextlib import closing
from datetime import datetime, timezone
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from stats_manager import track_scan
import aiohttp

# Timeout menunggu kunci DB (detik). SQLite akan menunggu daripada langsung
# error "database is locked" saat ada penulisan bersamaan.
DB_TIMEOUT = 30


def _connect():
    """Buka koneksi SQLite dengan timeout kunci."""
    return sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)

# -------- CONFIG --------
DB_PATH = "scans.db"
TEMPLATES_DIR = "templates"
TEMPLATE_FILES = [os.path.join(TEMPLATES_DIR, f"fourtis{i}.jpg") for i in range(1, 6)]
FONT_PATH = os.path.join("fonts", "Poppins-BoldItalic.ttf")
FONT_THIN_PATH = os.path.join("fonts", "arial.ttf")
COLOR_WHITE = (255, 255, 255)
COLOR_GREY = (180, 180, 180)
COLOR_GREEN = (0, 180, 80)
CLOUD_COLOR = (200, 200, 200)
COLOR_CHROME = (192, 192, 192)
NEON_GREEN_DARK = (0, 255, 100)
COLOR_RED = (220, 40, 40)
MAX_ALL_SCANS = 10
OUT_DIR = "generated_pnl"
os.makedirs(OUT_DIR, exist_ok=True)


# -------- DB --------
def init_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        cursor = conn.cursor()

        # Periksa apakah tabel 'scans' sudah ada
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            token_query TEXT,
            token_symbol TEXT,
            chain TEXT,
            mcap_at_scan REAL,
            scanned_at TIMESTAMP
        )
        """)
        conn.commit()

        # Periksa apakah kolom 'chat_id' sudah ada. Jika belum, tambahkan.
        try:
            cursor.execute("SELECT chat_id FROM scans LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE scans ADD COLUMN chat_id INTEGER")
            conn.commit()
    except Exception as e:
        # Jangan biarkan DB bermasalah menggagalkan import modul ini —
        # kalau import gagal, seluruh bot tidak bisa start.
        print(f"[WARN] init_db gagal: {e}")
    finally:
        if conn is not None:
            conn.close()


init_db()


def save_scan_row(user_id: int, username: str, token_query: str, token_symbol: str, chain: str, mcap: float, chat_id: int):
    with closing(_connect()) as conn:
        conn.execute("""INSERT INTO scans (user_id,username,token_query,token_symbol,chain,mcap_at_scan,scanned_at, chat_id)
                        VALUES (?,?,?,?,?,?,?,?)""",
                     (user_id, username, token_query, token_symbol, chain, float(mcap), datetime.now(timezone.utc), chat_id))
        conn.commit()


def get_latest_scan_for_user(user_id: int, token_query: Optional[str] = None):
    """
    Mengambil data scan terbaru untuk user, bisa berdasarkan token atau alamat.
    """
    with closing(_connect()) as conn:
        cur = conn.cursor()

        if token_query:
            # Definisikan pola regex untuk mendeteksi alamat kontrak
            # Ini akan mengenali alamat ETH/BSC (0x...), Solana, dan Tron
            contract_address_pattern = r'(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44}|T[a-zA-Z0-9]{33})'

            # Periksa apakah token_query adalah alamat kontrak
            if re.match(contract_address_pattern, token_query):
                # Jika itu alamat, cari di kolom 'token_query' yang menyimpan alamat asli.
                cur.execute(
                    "SELECT * FROM scans WHERE user_id=? AND token_query=? ORDER BY scanned_at DESC LIMIT 1",
                    (user_id, token_query)
                )
            else:
                # Jika itu bukan alamat (asumsikan itu simbol), cari di kolom 'token_symbol'.
                # Gunakan LOWER() untuk pencarian case-insensitive.
                cur.execute(
                    "SELECT * FROM scans WHERE user_id=? AND LOWER(token_symbol)=? ORDER BY scanned_at DESC LIMIT 1",
                    (user_id, token_query.lower())
                )
        else:
            # Jika tidak ada token_query, ambil scan terbaru milik user
            cur.execute("SELECT * FROM scans WHERE user_id=? ORDER BY scanned_at DESC LIMIT 1", (user_id,))

        return cur.fetchone()


def list_scans_for_user(user_id: int, limit: int = 20):
    with closing(_connect()) as conn:
        return conn.execute("SELECT id, token_query, token_symbol, chain, mcap_at_scan, scanned_at FROM scans WHERE user_id=? ORDER BY scanned_at DESC LIMIT ?",
                            (user_id, limit)).fetchall()


def list_scans_for_token(token_query: str, limit: int = MAX_ALL_SCANS):
    with closing(_connect()) as conn:
        return conn.execute("SELECT * FROM scans WHERE token_query=? ORDER BY scanned_at DESC LIMIT ?", (token_query, limit)).fetchall()


# -------- Utilities --------
def human_delta(ts: datetime) -> str:
    now = datetime.now(timezone.utc)
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except:
            return "unknown"
    diff = now - ts
    secs = int(diff.total_seconds())
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h {mins % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def fmt_mc(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except:
        return "N/A"
    if v >= 1e12:
        return f"${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.2f}M"
    if v >= 1e3:
        return f"${v / 1e3:.2f}K"
    return f"${v:.2f}"


# -------- Fetch current MCAP (reuse your project's APIs) --------
# This module assumes your project has DexScreenerAPI and CryptoPriceScannerBot available (as in main.py)
try:
    from main import DexScreenerAPI, CryptoPriceScannerBot, CoinMarketCapAPI
except Exception:
    DexScreenerAPI = None
    CryptoPriceScannerBot = None
    CoinMarketCapAPI = None


async def fetch_current_mcap(query: str) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Return (mcap_usd, token_symbol, chain_id) or (None,None,None) on failure.
    Tries major-coin path first (CryptoPriceScannerBot.is_major_coin), then DexScreener.
    """
    try:
        if CryptoPriceScannerBot:
            bot = CryptoPriceScannerBot()
            if bot.is_major_coin(query):
                # Try using coinmarketcap wrapper (CoinMarketCapAPI.get_major_coin_data)
                if CoinMarketCapAPI:
                    cmc = CoinMarketCapAPI()
                    maybe = await cmc.get_major_coin_data(query)
                    if maybe and maybe.get("market_cap") is not None:
                        return float(maybe.get("market_cap") or 0.0), maybe.get("symbol"), "major"
        if DexScreenerAPI:
            async with DexScreenerAPI() as api:
                results = await api.search_token(query)
                print(f"DEBUG: DexScreener API results for '{query}': {results}") # BARIS INI DITAMBAHKAN
                if not results:
                    return None, None, None
                # choose first pair
                pair = results[0]
                # DexScreener uses 'fdv' or 'marketCap' or similar
                fdv = pair.get("fdv") or pair.get("marketCap") or pair.get("market_cap") or 0
                base = pair.get("baseToken") or {}
                symbol = base.get("symbol") or base.get("name") or query
                chain = pair.get("chainId") or "unknown"
                try:
                    mcap_val = float(fdv or 0)
                except:
                    mcap_val = 0.0
                return mcap_val, symbol, chain
    except Exception as e:
        print("fetch_current_mcap error:", e)
        return None, None, None
    return None, None, None


# -------- Image rendering --------
def _text_size(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except:
        try:
            return font.getsize(text)
        except:
            return 0, 0


def _load_font(size: int, thin: bool = False):
    if thin and os.path.exists(FONT_THIN_PATH):
        try:
            return ImageFont.truetype(FONT_THIN_PATH, size)
        except:
            pass
    if os.path.exists(FONT_PATH):
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except:
            pass
    return ImageFont.load_default()


EXO2_FONT_PATH = os.path.join("fonts", "Montserrat-Black.ttf")


def _load_exo2_font(size: int):
    if os.path.exists(EXO2_FONT_PATH):
        try:
            return ImageFont.truetype(EXO2_FONT_PATH, size)
        except Exception as e:
            print("Failed to load Exo2 font:", e)
    return ImageFont.load_default()


def render_pnl_image(template_path: str, token_symbol: Optional[str],
                     mcap_at_scan: Optional[float], current_mcap: Optional[float],
                     username: str, scanned_at: datetime, token_query: str) -> Optional[str]:
    if not os.path.exists(template_path):
        return None
    try:
        img = Image.open(template_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        w, h = img.size

        # ---------- Fonts ----------
        font_symbol = _load_exo2_font(100)
        font_mcap = _load_font(38)
        font_pct = _load_font(135)
        font_meta = _load_font(32, thin=True)
        font_emoji = ImageFont.truetype(os.path.join("fonts", "seguiemj.ttf"), 32)

        pad_x = 90
        block_spacing = 40
        small_spacing = 15

        # Penyesuaian jarak vertikal untuk menggeser ke atas
        # Ubah nilai di sini untuk mengontrol jarak
        symbol_to_mcap_spacing = 20  # Jarak antara simbol dan MCAP
        mcap_to_pct_spacing = 10  # Jarak antara MCAP dan persentase

        # ---------- Hitung teks utama ----------
        symbol_text = f"${(token_symbol or 'TOKEN').upper()}"
        tw_sym, th_sym = _text_size(draw, symbol_text, font_symbol)

        mcap_scan_text = f"called at {fmt_mc(mcap_at_scan)}"
        tw_mscan, th_mscan = _text_size(draw, mcap_scan_text, font_mcap)

        mcap_now_text = f"MCAP (now) {fmt_mc(current_mcap)}"
        tw_mnow, th_mnow = _text_size(draw, mcap_now_text, font_mcap)

        pct = None
        try:
            if mcap_at_scan and current_mcap is not None:
                pct = 0.0 if float(mcap_at_scan) == 0 else ((float(current_mcap) - float(mcap_at_scan)) / float(
                    mcap_at_scan)) * 100
        except:
            pct = None

        pct_text = f"{abs(pct):.2f}%" if pct is not None else "N/A"
        tw_pct, th_pct = _text_size(draw, pct_text, font_pct)

        # ---------- Hitung total tinggi untuk center vertikal ----------
        total_height = th_sym + symbol_to_mcap_spacing + th_mscan + small_spacing + th_mnow + mcap_to_pct_spacing + th_pct
        start_y = (h - total_height) // 2 - 40

        # ---------- Draw symbol ----------
        draw.text((w - pad_x - tw_sym, start_y), symbol_text, font=font_symbol, fill=NEON_GREEN_DARK)

        # ---------- Draw MCAP ----------
        y = start_y + th_sym + symbol_to_mcap_spacing
        draw.text((w - pad_x - tw_mscan, y), mcap_scan_text, font=font_mcap, fill=COLOR_CHROME)
        y += th_mscan + small_spacing
        draw.text((w - pad_x - tw_mnow, y), mcap_now_text, font=font_mcap, fill=COLOR_GREY)

        # ---------- Draw percentage ----------
        y += th_mnow + mcap_to_pct_spacing

        # geser ke atas biar lebih rapih
        pct_offset = -40  # semakin negatif semakin ke atas
        draw.text(
            (w - pad_x - tw_pct, y + pct_offset),
            pct_text,
            font=font_pct,
            fill=COLOR_GREEN if (pct is not None and pct >= 0) else COLOR_RED
        )

        # ---------- Helper untuk emoji ----------
        def _draw_text_with_emoji(draw_obj, text, x, y, font_main, font_emoji, fill):
            cursor_x = x
            for c in text:
                font_to_use = font_emoji if ord(c) > 1000 else font_main
                cw, ch = _text_size(draw_obj, c, font_to_use)
                draw_obj.text((cursor_x, y), c, font=font_to_use, fill=fill)
                cursor_x += cw

        # ---------- User info ----------
        user_offset = 1
        time_offset = 2
        spacing_between = 10

        holder_text = f"  👤{username}"
        time_text = f"⏳{human_delta(scanned_at)} ago"

        tw_user, th_user = _text_size(draw, holder_text, font_meta)
        tw_time, th_time = _text_size(draw, time_text, font_meta)

        holder_x = w - pad_x - tw_user
        holder_y = y + th_pct + 20 + (user_offset * 10)
        time_x = holder_x - tw_time - spacing_between
        time_y = holder_y

        _draw_text_with_emoji(draw, time_text, time_x, time_y, font_meta, font_emoji, COLOR_GREY)
        _draw_text_with_emoji(draw, holder_text, holder_x, holder_y, font_meta, font_emoji, COLOR_GREY)

        # ---------- Save image ----------
        os.makedirs(OUT_DIR, exist_ok=True)
        # Perbaikan di sini: gunakan token_query jika token_symbol tidak ada
        safe_symbol = (token_symbol or token_query).replace(':', '_').replace('/', '_')
        out_fname = f"pnl_{safe_symbol}_{int(datetime.now().timestamp())}_{random.randint(0, 9999)}.png"
        out_path = os.path.join(OUT_DIR, out_fname)
        img.convert("RGB").save(out_path, format="PNG", optimize=True, quality=85)
        return out_path

    except Exception as e:
        print("render_pnl_image error:", e)
        return None


# -------- Telegram handlers (async) --------
# These handlers assume python-telegram-bot v20+ (async)
async def scan_command(update, context):
    """
    /scan <token/address>
    Save a snapshot of MCAP for the user.
    """
    if not context.args:
        await update.message.reply_text("Usage: /scan <token name or contract address>")
        return

    query = " ".join(context.args).strip()
    user = update.effective_user
    username = user.username or user.first_name or str(user.id)
    chat_id = update.effective_chat.id  # <-- DITAMBAHKAN

    loading = await update.message.reply_text(f"🔎 Scanning {query} ...")
    try:
        mcap, sym, chain = await fetch_current_mcap(query)
        if mcap is None:
            await loading.edit_text(f"❌ Could not fetch MCAP for `{query}`. Try contract address or token name.")
            return

        # chat_id diteruskan ke fungsi save (di thread agar tidak blok event loop)
        await asyncio.to_thread(save_scan_row, user.id, username, query, sym or query, chain or "unknown", float(mcap), chat_id)

        await loading.edit_text(f"✅ Saved scan for `{sym or query}` • MCAP: {fmt_mc(mcap)}")
    except Exception as e:
        await loading.edit_text(f"❌ Scan failed: {e}")


async def pnl_command(update, context):
    """
    /pnl [token/address]            -> user's latest scan
    /pnl all <token/address>        -> up to MAX_ALL_SCANS latest scans for that token (all users)
    """
    user = update.effective_user
    args = context.args or []
    token_arg = None

    def is_valid_address_or_symbol(query: str):
        # Pola regex yang diperbarui untuk alamat dan simbol
        pattern = r'(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44}|T[a-zA-Z0-9]{33}|^\$[a-zA-Z0-9]{2,10}$)'
        return bool(re.match(pattern, query))

    if len(args) >= 1 and args[0].lower() != "all":
        token_arg = " ".join(args).strip()
        if not is_valid_address_or_symbol(token_arg):
            await update.message.reply_text("The provided token or address is not valid.")
            return
    elif len(args) >= 2 and args[0].lower() == "all":
        # Logika untuk /pnl all tetap sama, tidak ada perubahan
        token_arg = " ".join(args[1:]).strip()
        if not token_arg:
            await update.message.reply_text("Usage: /pnl all <token|address>")
            return
        rows = await asyncio.to_thread(list_scans_for_token, token_arg, MAX_ALL_SCANS)
        if not rows:
            await update.message.reply_text(f"No saved scans found for {token_arg}.")
            return
        # Sisa kode untuk menampilkan daftar
        return
    else:
        # Tidak ada argumen, cari scan terbaru dari data sesi atau user
        if 'last_scanned_query' in context.user_data:
            token_arg = context.user_data['last_scanned_query']

    if not token_arg:
        await update.message.reply_text(
            "You have no saved scans. Please send a contract address, link, or use /scan <token> first.")
        return

    # --- PERBAIKAN DITAMBAHKAN DI SINI ---
    row = await asyncio.to_thread(get_latest_scan_for_user, user.id, token_arg)

    # Jika pencarian pertama gagal, coba resolusi alamat ke simbol
    if not row and is_valid_address_or_symbol(token_arg) and not token_arg.startswith('$'):
        try:
            # Ambil simbol dari alamat
            mcap_val, symbol, chain = await fetch_current_mcap(token_arg)
            if symbol:
                print(f"DEBUG: No direct match found, trying symbol '{symbol}' for address '{token_arg}'")
                row = await asyncio.to_thread(get_latest_scan_for_user, user.id, symbol)
        except Exception as e:
            print(f"DEBUG: Failed to resolve address to symbol: {e}")

    # Akhirnya, periksa apakah baris ditemukan
    if not row:
        await update.message.reply_text(f"No saved scans found for {token_arg}.")
        return

    # --- SISA KODE (TETAP SAMA) ---
    _, _, username, token_query, token_symbol, chain, mcap_at_scan, scanned_at, chat_id = row
    if isinstance(scanned_at, str):
        try:
            scanned_at_dt = datetime.fromisoformat(scanned_at)
        except:
            try:
                scanned_at_dt = datetime.strptime(scanned_at, "%Y-%m-%d %H:%M:%S.%f")
            except:
                scanned_at_dt = datetime.now(timezone.utc)
    else:
        scanned_at_dt = scanned_at

    loading = await update.message.reply_text("Generating PNL image...")
    try:
        current_mcap, cur_sym, cur_chain = await fetch_current_mcap(token_query)
        if current_mcap is None:
            await loading.edit_text("❌ Could not fetch current MCAP for the token/address.")
            return
        template_path = random.choice(TEMPLATE_FILES)
        # Render gambar PNL berat (PIL + font) → jalankan di thread supaya
        # tidak membekukan event loop dan membuat bot "hang" untuk semua user.
        out_path = await asyncio.to_thread(
            render_pnl_image, template_path, token_symbol or cur_sym or token_query,
            float(mcap_at_scan or 0.0), float(current_mcap), username, scanned_at_dt,
            token_query
        )
        if not out_path:
            await loading.edit_text("❌ Failed to render image (missing template?).")
            return
        await loading.delete()
        with open(out_path, "rb") as fh:
            await update.message.reply_photo(photo=fh)
        try:
            os.remove(out_path)
        except:
            pass
    except Exception as e:
        await loading.edit_text(f"❌ Error generating PNL image: {e}")

async def list_scans_command(update, context):
    user = update.effective_user
    rows = await asyncio.to_thread(list_scans_for_user, user.id, 20)
    if not rows:
        await update.message.reply_text("You have no saved scans. Use /scan <token> to create one.")
        return
    lines = []
    for r in rows:
        _id, token_query, token_symbol, chain, mcap_at_scan, scanned_at = r
        if isinstance(scanned_at, str):
            try:
                scanned_dt = datetime.fromisoformat(scanned_at)
            except:
                scanned_dt = scanned_at
        else:
            scanned_dt = scanned_at
        lines.append(f"• {token_symbol} ({token_query}) • MCAP: {fmt_mc(mcap_at_scan)} • {human_delta(scanned_dt)} ago")
    text = "Your scans:\n" + "\n".join(lines)
    # Telegram has length limits; split if necessary
    for chunk in [text[i:i + 3800] for i in range(0, len(text), 3800)]:
        await update.message.reply_text(chunk)


async def process_and_save_scan(update, context, token_query: str):
    """
    Fungsi pembantu untuk memproses dan menyimpan scan token ke database DAN memperbarui statistik.
    """
    user = update.effective_user
    username = user.username or user.first_name or str(user.id)
    chat_id = update.effective_chat.id

    try:
        mcap, sym, chain = await fetch_current_mcap(token_query)
        if mcap is not None:
            # ✅ Tindakan 1: Simpan data ke database (untuk /pnl) — di thread.
            await asyncio.to_thread(
                save_scan_row,
                user.id,
                username,
                token_query,
                sym or token_query,
                chain or "unknown",
                float(mcap),
                chat_id
            )
            print(f"Saved scan for {token_query} in chat {chat_id}")

            # ✅ Tindakan 2: Perbarui statistik (untuk /status)
            await track_scan(token_address=None, chain=chain or "UNKNOWN")

            return True, f"✅ Saved scan for `{sym or token_query}` • MCAP: {fmt_mc(mcap)}"
        else:
            return False, f"❌ Could not fetch MCAP for `{token_query}`."
    except Exception as e:
        print("Error processing and saving scan:", e)
        return False, f"❌ Scan failed: {e}"