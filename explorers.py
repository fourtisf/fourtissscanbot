# =============================================================================
# explorers.py - Async token holders fetchers
# =============================================================================
import os
import asyncio
import aiohttp
from typing import Optional
import re
import logging

logger = logging.getLogger(__name__)

# ----------------------- Async LRU Cache -----------------------
def async_lru(ttl_seconds: int = 600):
    """Simple in-process async cache decorator."""
    def _decorator(func):
        cache = {}
        lock = asyncio.Lock()

        async def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = asyncio.get_event_loop().time()
            async with lock:
                entry = cache.get(key)
                if entry:
                    ts, value = entry
                    if now - ts < ttl_seconds:
                        return value
                value = await func(*args, **kwargs)
                cache[key] = (now, value)
                return value
        return wrapper
    return _decorator

# ----------------------- Main Function -----------------------
@async_lru(ttl_seconds=600)
async def get_holders_by_address(address: str, chain: str) -> Optional[int]:
    """
    Return holder count (int) for token contract address on given chain.
    Supported chains: 'ethereum', 'bsc', 'base', 'solana', 'tron'
    Returns None if unknown/unavailable.
    """
    if not address:
        return None
    address = address.strip()
    chain = (chain or "").lower()

    try:
        if chain in ("ethereum", "eth"):
            return await _holders_etherscan(address, chain_id=1, site="https://etherscan.io")
        if chain in ("bsc", "bnb", "binance"):
            return await _holders_etherscan(address, chain_id=56, site="https://bscscan.com")
        if chain == "base":
            return await _holders_etherscan(address, chain_id=8453, site="https://basescan.org")
        if chain in ("solana", "sol"):
            return await _holders_solscan(address)
        if chain == "tron":
            return await _holders_tronscan(address)
    except Exception as e:
        logger.warning(f"holders lookup failed ({chain} {address}): {e}")
        return None

    return None

# ----------------------- Etherscan V2 helper (ETH / BSC / Base, satu key) -----------------------
async def _holders_etherscan(address: str, chain_id: int, site: str) -> Optional[int]:
    key = os.getenv("ETHERSCAN_API_KEY")

    if key:
        try:
            url = (f"https://api.etherscan.io/v2/api?chainid={chain_id}"
                   f"&module=token&action=tokeninfo&contractaddress={address}&apikey={key}")
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=8) as resp:
                    if resp.status == 200:
                        j = await resp.json()
                        res = j.get("result")
                        if isinstance(res, list) and res:
                            res = res[0]
                        if isinstance(res, dict):
                            holders = res.get("holders") or res.get("holderCount") or res.get("holder_count")
                            if holders:
                                try:
                                    return int(holders)
                                except Exception:
                                    pass
        except Exception as e:
            logger.warning(f"holders request failed ({url.split('?')[0]}): {e}")

    # Fallback: scrape halaman explorer (tanpa key)
    try:
        url = f"{site}/token/{address}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=8) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    m = re.search(r'Holders</span>\s*<span[^>]*>\s*([0-9,]+)', text) \
                        or re.search(r'"holders"\s*:\s*([0-9,]+)', text)
                    if m:
                        return int(m.group(1).replace(",", ""))
    except Exception as e:
        logger.warning(f"holders request failed ({url.split('?')[0]}): {e}")

    return None

# ----------------------- SolScan helpers -----------------------
async def _holders_solscan(address: str) -> Optional[int]:
    try:
        url = f"https://public-api.solscan.io/token/meta?tokenAddress={address}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=8) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    holders = j.get("holders") or j.get("holdersCount") or j.get("holderCount")
                    if holders:
                        try:
                            return int(holders)
                        except Exception:
                            pass
    except Exception as e:
        logger.warning(f"holders request failed ({url.split('?')[0]}): {e}")
    return None

# ----------------------- Tron: Tronscan helpers -----------------------
async def _holders_tronscan(address: str) -> Optional[int]:
    try:
        url = f"https://apilist.tronscan.org/api/token?id={address}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=8) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    holders = j.get("holders") or j.get("holderCount") or j.get("holder_count")
                    if holders:
                        try:
                            return int(holders)
                        except Exception:
                            pass
    except Exception as e:
        logger.warning(f"holders request failed ({url.split('?')[0]}): {e}")
    return None
