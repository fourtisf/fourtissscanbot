import re
import aiohttp
import logging

logger = logging.getLogger(__name__)
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict
from explorers import get_holders_by_address

# ============================================================
# Config & Constants
# ============================================================

_CACHE: Dict[str, Dict] = {}
_TTL = timedelta(minutes=10)

DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# ==== Bot trading Solana ====
from config import SOL_BOT_TRADING  # satu sumber: link referral fourtis


# ============================================================
# Helpers
# ============================================================

async def _fetch_json(session: aiohttp.ClientSession, url: str, timeout: int = 15, headers: Optional[Dict] = None):
    try:
        async with session.get(url, timeout=timeout, headers=headers) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.warning(f"fetch failed {url.split('?')[0]}: {e}")
        return None
    return None


def _explorer_for(chain: str, address: str) -> Optional[str]:
    chain = (chain or "").lower()
    if not address:
        return None
    if ETH_ADDR_RE.match(address):
        if chain == "ethereum":
            return f"https://etherscan.io/token/{address}"
        if chain in ("bsc", "bnb"):
            return f"https://bscscan.com/token/{address}"
        if chain == "base":
            return f"https://basescan.org/token/{address}"
        if chain in ("polygon", "matic"):
            return f"https://polygonscan.com/token/{address}"
    if chain == "tron":
        return f"https://tronscan.org/#/token/{address}"
    if chain == "solana" and BASE58_RE.match(address):
        return f"https://solscan.io/token/{address}"
    return None


def _normalize_url(u: str, prefix: str) -> Optional[str]:
    if not u:
        return None
    if u.startswith("http"):
        return u
    return prefix + u.lstrip("@/")


# ============================================================
# Core: Get Token Links + Stats
# ============================================================

async def get_token_links(address: str, chain: str = "ethereum") -> Dict[str, Optional[object]]:
    if not address:
        return {}

    key = f"{chain}:{address.lower()}"
    now = datetime.utcnow()

    cached = _CACHE.get(key)
    if cached and now - cached["_ts"] < _TTL:
        return cached["data"]

    result = {
        "website": None,
        "twitter": None,
        "telegram": None,
        "discord": None,
        "token_explorer": None,
        "pair_explorers": [],
        "holders": None,
        "market_cap": None,
        "fdv": 0,
        "bot_trading": None,
        # stats dari Dexscreener
        "liquidity": 0,
        "volume_5m": 0,
        "volume_1h": 0,
        "volume_6h": 0,
        "volume_24h": 0,
        "txns_5m": 0,
        "txns_1h": 0,
        "txns_6h": 0,
        "txns_24h": 0,
        "makers_24h": 0,
        "buyers_24h": 0,
        "sellers_24h": 0,
        "buys_24h": 0,
        "sells_24h": 0,
        "buy_volume_24h": 0,
        "sell_volume_24h": 0,
        "ath": 0,
        "age_days": 0,
        "views": 0,
    }

    async with aiohttp.ClientSession() as session:
        try:
            ds_url = DEXSCREENER_TOKEN_URL.format(address=address)
            ds = await _fetch_json(session, ds_url)
            if ds and isinstance(ds, dict):
                token_meta = ds.get("token") or {}

                # --- holders ---
                holders = token_meta.get("holders") or token_meta.get("holderCount")
                if holders:
                    try:
                        result["holders"] = int(holders)
                    except Exception:
                        result["holders"] = holders

                # --- market cap ---
                market_cap = token_meta.get("marketCap") or token_meta.get("market_cap")
                if market_cap:
                    try:
                        result["market_cap"] = float(market_cap)
                    except Exception:
                        result["market_cap"] = market_cap

                # --- fallback holders from explorer ---
                if not result.get("holders") and address:
                    try:
                        holders_from_explorer = await get_holders_by_address(address, chain=chain)
                        if holders_from_explorer:
                            result["holders"] = holders_from_explorer
                    except Exception:
                        pass

                # --- pilih pair terbaik (likuiditas terbesar) ---
                pairs = ds.get("pairs") or []
                best_pair = None
                max_liq = 0
                for p in pairs:
                    liq = p.get("liquidity", {}).get("usd") or 0
                    if liq > max_liq:
                        max_liq = liq
                        best_pair = p

                if best_pair:
                    # --- stats utama ---
                    result["liquidity"] = best_pair.get("liquidity", {}).get("usd") or 0
                    result["fdv"] = best_pair.get("fdv") or 0
                    result["market_cap"] = best_pair.get("marketCap") or result.get("market_cap")

                    # --- volume & txns ---
                    result["volume_5m"] = best_pair.get("volume", {}).get("m5") or 0
                    result["volume_1h"] = best_pair.get("volume", {}).get("h1") or 0
                    result["volume_6h"] = best_pair.get("volume", {}).get("h6") or 0
                    result["volume_24h"] = best_pair.get("volume", {}).get("h24") or 0

                    result["txns_5m"] = best_pair.get("txns", {}).get("m5") or 0
                    result["txns_1h"] = best_pair.get("txns", {}).get("h1") or 0
                    result["txns_6h"] = best_pair.get("txns", {}).get("h6") or 0
                    result["txns_24h"] = best_pair.get("txns", {}).get("h24") or 0

                    # --- buyers / sellers / trades ---
                    result["makers_24h"] = best_pair.get("makers", {}).get("h24") or 0
                    result["buyers_24h"] = best_pair.get("buyers", {}).get("h24") or 0
                    result["sellers_24h"] = best_pair.get("sellers", {}).get("h24") or 0
                    result["buys_24h"] = best_pair.get("buys", {}).get("h24") or 0
                    result["sells_24h"] = best_pair.get("sells", {}).get("h24") or 0
                    result["buy_volume_24h"] = best_pair.get("buyVolume", {}).get("h24") or 0
                    result["sell_volume_24h"] = best_pair.get("sellVolume", {}).get("h24") or 0

                    # --- ATH, umur, views ---
                    info = best_pair.get("info") or {}
                    result["ath"] = float(info.get("athPriceUsd") or 0)
                    result["age_days"] = info.get("ageDays") or 0
                    result["views"] = info.get("views") or 0

                    # --- website & socials dari info ---
                    for w in info.get("websites", []):
                        if w.get("url") and not result["website"]:
                            result["website"] = w["url"]

                    for s in info.get("socials", []):
                        t = (s.get("type") or "").lower()
                        u = s.get("url")
                        if not u:
                            continue
                        if t == "twitter" and not result["twitter"]:
                            result["twitter"] = u
                        elif t == "telegram" and not result["telegram"]:
                            result["telegram"] = u
                        elif t == "discord" and not result["discord"]:
                            result["discord"] = u

                    # --- pair explorer ---
                    if "pairAddress" in best_pair:
                        ex = _explorer_for(chain, best_pair["pairAddress"])
                        if ex:
                            result["pair_explorers"].append(ex)

        except Exception as e:
            print(f"⚠️ Error fetch Dexscreener: {e}")

    # --- fallback explorer ---
    result["token_explorer"] = _explorer_for(chain, address)
    result["pair_explorers"] = list(dict.fromkeys(result["pair_explorers"]))

    # --- Solana bot trading ---
    if chain.lower() == "solana":
        bots = [f"[{name}]({url.format(addr=address)})" for name, url in SOL_BOT_TRADING]
        if bots:
            result["bot_trading"] = " • ".join(bots)

    # --- cache result ---
    _CACHE[key] = {"_ts": datetime.utcnow(), "data": result}
    return result


# ============================================================
# Example Usage
# ============================================================

async def main():
    test_cases = [
        ("ethereum", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
        ("bsc", "0xe9e7cea3dedca5984780bafc599bd69add087d56"),
        ("base", "0x4200000000000000000000000000000000000006"),
        ("tron", "TVAEYCmc15awaDRAjUZ1KfRYxRW5gn5vCM"),
        ("solana", "So11111111111111111111111111111111111111112"),
    ]
    for chain, addr in test_cases:
        print(f"\n===== {chain.upper()} | {addr} =====")
        links = await get_token_links(addr, chain)
        print(links)

if __name__ == "__main__":
    asyncio.run(main())
