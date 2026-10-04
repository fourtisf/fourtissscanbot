import asyncio
import aiohttp
import logging
import time
from datetime import datetime, timedelta
import json
from pair_scanner import detect_pair_address
from typing import Any, Dict, List, Optional, Tuple
import plotly.graph_objects as go
from promo_manager import get_custom_report
from security_helper import get_security_info
import plotly.io as pio
from io import BytesIO

from globals import admin_manager
import base64
import random
from stats_manager import load_stats
from stats_manager import track_scan
from PIL import Image
from promo_manager import get_custom_report

import os
import re
from config import Config, SOL_BOT_TRADING
from admin_report_manager import AdminReportManager
from utils import format_custom_emoji
from telegram.helpers import escape_markdown
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from token_links import get_token_links
from chart_renderer import compress_image
from explorers import get_holders_by_address
from chart_renderer import ChartRenderer
#from pnl_manager import save_scan_row, human_delta, fmt_mc


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def detect_query_type(query: str) -> Tuple[str, Optional[str]]:
    """
    Deteksi tipe query user.
    Return: (tipe, value)
    tipe: "pair", "contract", "url", "symbol"
    """
    query = query.strip()

    # 🔹 Pola Dexscreener URL
    match = re.match(r"https?://dexscreener\.com/(\w+)/([a-zA-Z0-9]+)", query)
    if match:
        chain = match.group(1)
        value = match.group(2)
        # cek apakah address atau pair
        if value.startswith("0x") or re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", value):
            return "url", value

    # 🔹 Pair ID (Solana, Tron, Base, BSC dll.)
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", query):
        return "pair", query

    # 🔹 Contract Address (EVM + Tron + Solana mint)
    if re.match(r"^0x[a-fA-F0-9]{40}$", query):
        return "contract", query
    if re.match(r"^T[a-zA-Z0-9]{33}$", query):  # Tron
        return "contract", query
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", query):  # Solana Mint
        return "contract", query

    # 🔹 Default → anggap symbol
    return "symbol", query

# --- SECURITY HELPER ---
def compress_image(input_path, output_path, max_size=(1280, 720), quality=85):
    """Compress screenshot biar ukuran lebih kecil"""
    img = Image.open(input_path)
    img.thumbnail(max_size, Image.LANCZOS)
    img.save(output_path, format="PNG", optimize=True, quality=quality)

# --- Helper escape MarkdownV2 ---
def escape_md2(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(r"([{}])".format(re.escape(escape_chars)), r"\\\1", text)


def format_admin_reports(manager) -> str:
    """
    Convert admin reports into a nicely formatted inline string.
    """
    if not hasattr(manager, "reports") or not manager.reports:
        return ""

    lines = []
    for name, link in manager.reports.items():  # assuming reports is a dict {name: link}
        lines.append(f"• [{name}]({link})")

    return "📋 Admin Reports:\n" + "\n".join(lines)


class CryptoBotConfig:
    """Configuration class for the crypto bot - focused on 5 main blockchains"""

    def __init__(self):

        self.CUSTOM_EMOJI_IDS = {
            "alarm": {
                "char": "⏰",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6141206421804422655"}]
            },
            "diamond": {
                "char": "🔮",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6141179956215945350"}]
            },
            "chart": {
                "char": "📈",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140812337080179629"}]
            },
            "memo": {
                "char": "📝",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140861398491601488"}]
            },
            "cross": {
                "char": "❌",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140737359836092241"}]
            },
            "idea": {
                "char": "💡",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140764546979076674"}]
            },
            "link": {
                "char": "🔗",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143122866276668612"}]
            },
            "droplet": {
                "char": "💧",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140719492772141505"}]
            },
            "repeat": {
                "char": "🫄",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140832965808101595"}]
            },
            "bank": {
                "char": "🏦",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143439701719127874"}]
            },
            "money": {
                "char": "💰",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140830457547201260"}]
            },
            "trophy": {
                "char": "🏆",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6142917085803583964"}]
            },
            "rocket": {
                "char": "🚀",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143461438548613604"}]
            },
            "magnifier": {
                "char": "🔎",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140757460283039555"}]
            },
            "stopwatch": {
                "char": "⏱️",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140850987490876092"}]
            },
            "chart_down": {
                "char": "📋",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140914578776660570"}]
            },
            "neutral_face": {
                "char": "😐",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6142954215795856741"}]
            },
            "chart_up": {
                "char": "📈",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140949342241954628"}]
            },
            "diamond2": {
                "char": "💎",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143191839156475840"}]
            },
            "warning": {
                "char": "⚠️",
                "entities": [
                    {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143413717166987295"}]
            }
        }

    CUSTOM_EMOJI_IDS = Config.CUSTOM_EMOJI_IDS

    BOT_CTA_LIST = [
        ("FOU1", "🚀 Launch your token with Fourtis!", "https://t.me/fourtistechbot"),
        ("FOU2", "⚡ Boost your token on Fourtis!", "https://t.me/fourtistechbot"),
        ("FOU3", "🔥 List instantly via Fourtis!", "https://t.me/fourtistechbot"),
        ("FOU4", "🎯 Grow your token with Fourtis!", "https://t.me/fourtistechbot"),
        ("FOU5", "💥 Get listed fast on Fourtis!", "https://t.me/fourtistechbot"),
    ]

    BLOCKCHAINS = {
        'ethereum': {'name': '🔷 Ethereum', 'symbol': 'ETH', 'chain_id': 'ethereum'},
        'bsc': {'name': '🟡 BSC', 'symbol': 'BNB', 'chain_id': 'bsc'},
        'solana': {'name': '🟣 Solana', 'symbol': 'SOL', 'chain_id': 'solana'},
        'base': {'name': '🔵 Base', 'symbol': 'BASE', 'chain_id': 'base'},
        'tron': {'name': '🔴 Tron', 'symbol': 'TRX', 'chain_id': 'tron'}
    }

    MAJOR_COINS = {
        'bitcoin': {'symbol': 'BTC', 'cmc_id': 1},
        'ethereum': {'symbol': 'ETH', 'cmc_id': 1027},
        'binancecoin': {'symbol': 'BNB', 'cmc_id': 1839},
        'solana': {'symbol': 'SOL', 'cmc_id': 5426},
        'tron': {'symbol': 'TRX', 'cmc_id': 1958}
    }

    # Time intervals for charts
    TIME_INTERVALS = {
        '1s': {'name': '1 Second', 'minutes': 0.0167},
        '1m': {'name': '1 Minute', 'minutes': 1},
        '3m': {'name': '3 Minutes', 'minutes': 3},
        '5m': {'name': '5 Minutes', 'minutes': 5},
        '15m': {'name': '15 Minutes', 'minutes': 15},
        '30m': {'name': '30 Minutes', 'minutes': 30},
        '1h': {'name': '1 Hour', 'minutes': 60},
        '2h': {'name': '2 Hours', 'minutes': 120},
        '4h': {'name': '4 Hours', 'minutes': 240},
        '8h': {'name': '8 Hours', 'minutes': 480},
        '12h': {'name': '12 Hours', 'minutes': 720},
        '1d': {'name': '1 Day', 'minutes': 1440},
        '3d': {'name': '3 Days', 'minutes': 4320},
        '1w': {'name': '1 Week', 'minutes': 10080},
        '2w': {'name': '2 Weeks', 'minutes': 20160},
        '1m': {'name': '1 Month', 'minutes': 43200}
    }

    DEXSCREENER_BASE_URL = "https://api.dexscreener.com/latest"
    COINMARKETCAP_API = "https://pro-api.coinmarketcap.com/v1"
    FEAR_GREED_API = "https://api.alternative.me/fng/"


# main.py

# ... kode yang sudah ada ...
class CoinMarketCapAPI:
    """Handler for CoinMarketCap API for accurate major coin data"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('COINMARKETCAP_API_KEY')
        self.base_url = CryptoBotConfig.COINMARKETCAP_API

    async def get_major_coin_data(self, symbol: str) -> Optional[Dict]:
        """Get accurate data for major coins from CoinMarketCap with custom emojis"""
        # ... kode yang sudah ada untuk fungsi ini ...

        try:
            symbol_lower = symbol.lower()
            CE = Config.CUSTOM_EMOJI_IDS
            coin_info = None
            for coin_key, coin_data in CryptoBotConfig.MAJOR_COINS.items():
                if (coin_data['symbol'].lower() == symbol_lower or
                        coin_key == symbol_lower or
                        symbol_lower in coin_key):
                    coin_info = coin_data
                    break
            if not coin_info:
                return None

            # Use CoinGecko if no API key
            if not self.api_key:
                # ... kode CoinGecko yang sudah ada ...
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.coingecko.com/api/v3/simple/price"
                    params = {
                        'ids': coin_key,
                        'vs_currencies': 'usd',
                        'include_24hr_change': 'true',
                        'include_market_cap': 'true',
                        'include_24hr_vol': 'true'
                    }

                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if coin_key in data:
                                coin_data = data[coin_key]
                                return {
                                    'symbol': coin_info['symbol'],
                                    'name': coin_key.title(),
                                    'price': coin_data.get('usd', 0),
                                    'percent_change_24h': coin_data.get('usd_24h_change', 0),
                                    'market_cap': coin_data.get('usd_market_cap', 0),
                                    'volume_24h': coin_data.get('usd_24h_vol', 0),
                                    'rank': 1 if coin_info['symbol'] == 'BTC' else 2 if coin_info[
                                                                                            'symbol'] == 'ETH' else 3,
                                    'emoji_chart': format_custom_emoji(CE['chart'])[0],
                                    'entities_chart': format_custom_emoji(CE['chart'])[1],
                                    'emoji_money': format_custom_emoji(CE['money'])[0],
                                    'entities_money': format_custom_emoji(CE['money'])[1],
                                    'emoji_rocket': format_custom_emoji(CE['rocket'])[0],
                                    'entities_rocket': format_custom_emoji(CE['rocket'])[1]
                                }

            else:
                # Use CoinMarketCap API if key available
                headers = {'X-CMC_PRO_API_KEY': self.api_key}
                async with aiohttp.ClientSession(headers=headers) as session:
                    url = f"{self.base_url}/cryptocurrency/quotes/latest"
                    params = {'id': coin_info['cmc_id']}

                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            coin_data = data['data'][str(coin_info['cmc_id'])]
                            quote = coin_data['quote']['USD']

                            return {
                                'symbol': coin_data['symbol'],
                                'name': coin_data['name'],
                                'price': quote['price'],
                                'percent_change_24h': quote['percent_change_24h'],
                                'market_cap': quote['market_cap'],
                                'volume_24h': quote['volume_24h'],
                                'rank': coin_data['cmc_rank'],
                                'emoji_chart': format_custom_emoji(CE['chart'])[0],
                                'entities_chart': format_custom_emoji(CE['chart'])[1],
                                'emoji_money': format_custom_emoji(CE['money'])[0],
                                'entities_money': format_custom_emoji(CE['money'])[1],
                                'emoji_rocket': format_custom_emoji(CE['rocket'])[0],
                                'entities_rocket': format_custom_emoji(CE['rocket'])[1]
                            }

            return None

        except Exception as e:
            logger.error(f"CoinMarketCap API error: {e}")
            return None

    # ✅ FUNGSI BARU UNTUK MENDAPATKAN ATH MARKETCAP
    async def get_ath_marketcap(self, cmc_id: int) -> Optional[float]:
        """
        Mengambil ATH Marketcap dari data historis CoinMarketCap.
        Menggunakan endpoint cryptocurrency/quotes/historical
        """
        if not self.api_key:
            return None  # Tidak bisa mendapatkan data historis tanpa API key

        try:
            headers = {'X-CMC_PRO_API_KEY': self.api_key}
            async with aiohttp.ClientSession(headers=headers) as session:
                url = f"{self.base_url}/cryptocurrency/quotes/historical"
                params = {
                    "id": cmc_id,
                    "time_start": "2010-01-01T00:00:00.000Z",  # Dari tanggal paling awal
                    "interval": "monthly"  # Interval bulanan untuk mengurangi jumlah panggilan
                }

                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if data and data['status']['error_code'] == 0:
                        historical_data = data['data'][str(cmc_id)]['quotes']
                        ath_marketcap = 0
                        for record in historical_data:
                            # Langsung ambil nilai marketcap yang sudah dihitung oleh CMC
                            market_cap = record['quote']['USD']['market_cap']
                            if market_cap > ath_marketcap:
                                ath_marketcap = market_cap
                        return ath_marketcap
        except Exception as e:
            logger.error(f"Error fetching historical marketcap for CMC ID {cmc_id}: {e}")
            return None
        return None


# ... kode lainnya ...

# ---------- Cache DexScreener (hemat rate limit; banyak user scan token yang sama) ----------
_DS_CACHE: Dict[str, Tuple[float, Any]] = {}
_DS_CACHE_TTL = 30  # detik
_DS_CACHE_MAX = 1000


class _CachedResponse:
    def __init__(self, status: int, data: Any):
        self.status = status
        self._data = data

    async def json(self, *args, **kwargs):
        return self._data


class _CachedGet:
    def __init__(self, session: aiohttp.ClientSession, url: str):
        self._session = session
        self._url = url

    async def __aenter__(self):
        now = time.monotonic()
        hit = _DS_CACHE.get(self._url)
        if hit and now - hit[0] < _DS_CACHE_TTL:
            return _CachedResponse(200, hit[1])

        async with self._session.get(self._url) as r:
            status = r.status
            data = await r.json(content_type=None) if status == 200 else None
        if status == 200:
            if len(_DS_CACHE) >= _DS_CACHE_MAX:
                _DS_CACHE.clear()
            _DS_CACHE[self._url] = (now, data)
        elif status == 429:
            logger.warning(f"DexScreener rate limit (429): {self._url}")
        return _CachedResponse(status, data)

    async def __aexit__(self, *exc):
        return False


class _CachingSession:
    """Bungkus aiohttp session: GET ke DexScreener di-cache selama _DS_CACHE_TTL detik."""

    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    def get(self, url: str, **kwargs):
        if kwargs:
            return self._session.get(url, **kwargs)
        return _CachedGet(self._session, url)

    async def close(self):
        await self._session.close()


class DexScreenerAPI:
    """Handler for DexScreener API interactions - all data from DexScreener only"""
    BASE_URL = "https://api.dexscreener.com/latest/dex"

    def __init__(self):
        self.base_url = self.BASE_URL
        self.session = None

    async def __aenter__(self):
        self.session = _CachingSession(aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def detect_contract_address(self, query: str) -> Tuple[Optional[str], str, str]:
        CE = Config.CUSTOM_EMOJI_IDS
        query = query.strip()

        # ✅ Perbaikan: Deteksi alamat Solana
        if 32 <= len(query) <= 44 and not query.startswith(('0x', 'T')) and re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$',
                                                                                     query):
            return 'solana', query, CE.get('bank', {}).get('char', '🏦')

        # ✅ Perbaikan: Deteksi alamat EVM
        if re.match(r'^0x[a-fA-F0-9]{40}$', query):
            return 'ethereum', query, CE.get('diamond', {}).get('char', '💎')

        # ✅ Perbaikan: Deteksi alamat Tron
        if re.match(r'^T[a-zA-Z0-9]{33}$', query):
            return 'tron', query, CE.get('rocket', {}).get('char', '🚀')

        return None, query, CE.get('warning', {}).get('char', '⚠️')

    async def search_token(self, query: str) -> list:
        CE = Config.CUSTOM_EMOJI_IDS
        all_pairs = []

        try:
            detected_chain, address, _ = self.detect_contract_address(query)

            # 🚀 Case 1: Pair ID langsung (32–44 char, bukan hex)
            if not detected_chain and re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", query):
                for chain in CryptoBotConfig.BLOCKCHAINS:
                    try:
                        url = f"{self.base_url}/pairs/{chain}/{query}"
                        logger.info(f"{CE['magnifier']['char']} Searching pair {query} on {chain}: {url}")
                        async with self.session.get(url) as response:
                            if response.status == 200:
                                data = await response.json()
                                if data and data.get("pairs"):
                                    for pair in data["pairs"]:
                                        all_pairs.append(pair)
                                        logger.info(f"{CE['alarm']['char']} Added {chain} pair via /pairs.")
                                    break  # stop kalau sudah ketemu
                    except Exception as e:
                        logger.error(f"{CE['cross']['char']} Error searching pair {query} on {chain}: {e}")

            # 🚀 Case 2: Nama/simbol biasa
            elif not detected_chain:
                url = f"{self.base_url}/search/?q={query}"
                logger.info(f"{CE['magnifier']['char']} Searching by name/symbol: {url}")
                async with self.session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            filtered_pairs = [
                                pair for pair in pairs
                                if pair.get("quoteToken", {}).get("symbol", "").upper() in
                                   ["USDT", "USDC", "USD", "BUSD", "DAI", "WETH", "BNB", "SOL", "TRX"]
                                   and pair.get("chainId", "") in CryptoBotConfig.BLOCKCHAINS
                            ]
                            return filtered_pairs[:10]

            # 🚀 Case 3: Contract address
            else:
                logger.info(f"{CE['idea']['char']} Detected {detected_chain} contract: {address}")
                chains_to_search = []
                if detected_chain == "solana":
                    chains_to_search = ["solana"]
                elif detected_chain == "ethereum":
                    chains_to_search = ["ethereum", "bsc", "base"]
                elif detected_chain == "tron":
                    chains_to_search = ["tron"]

                for chain in chains_to_search:
                    # 1️⃣ via /tokens
                    try:
                        url = f"{self.base_url}/tokens/{address}"
                        logger.info(f"{CE['magnifier']['char']} Searching {chain} via /tokens: {url}")
                        async with self.session.get(url) as response:
                            if response.status == 200:
                                data = await response.json()
                                if data and data.get("pairs"):
                                    for pair in data["pairs"]:
                                        all_pairs.append(pair)
                                        logger.info(f"{CE['alarm']['char']} Added {chain} pair from /tokens.")
                    except Exception as e:
                        logger.error(f"{CE['cross']['char']} Error searching {chain} via /tokens: {e}")

                    # 2️⃣ via /search fallback
                    try:
                        search_url = f"{self.base_url}/search/?q={address}"
                        logger.info(f"{CE['magnifier']['char']} Searching {chain} via /search: {search_url}")
                        async with self.session.get(search_url) as search_response:
                            if search_response.status == 200:
                                search_data = await search_response.json()
                                if search_data and search_data.get("pairs"):
                                    for pair in search_data["pairs"]:
                                        if pair.get("baseToken", {}).get("address", "").lower() == address.lower():
                                            all_pairs.append(pair)
                                            logger.info(f"{CE['rocket']['char']} Found {chain} pair from /search.")
                    except Exception as e:
                        logger.error(f"{CE['cross']['char']} Error searching {chain} via /search: {e}")

            # 🔁 Deduplicate by pairAddress
            unique_pairs = []
            seen_addresses = set()
            for pair in all_pairs:
                pair_addr = pair.get("pairAddress", "")
                if pair_addr and pair_addr not in seen_addresses:
                    unique_pairs.append(pair)
                    seen_addresses.add(pair_addr)

            return unique_pairs[:5]

        except Exception as e:
            logger.error(f"{CE['cross']['char']} General error searching token {query}: {e}")
            return []

    async def get_pair_by_id(self, chain: str, pair_address: str):
        url = f"{self.BASE_URL}/pairs/{chain}/{pair_address}"
        async with self.session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


    async def get_pair_info(self, pair_address: str, chain_id: str) -> Optional[Dict]:
        """Mengambil informasi pair dari DexScreener API berdasarkan alamat pair."""
        url = f"{self.base_url}/pairs/{chain_id}/{pair_address}"
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('pairs'):
                        return data['pairs'][0]
        except Exception as e:
            logger.error(f"DexScreener pair search error: {e}", exc_info=True)
        return None

    async def get_trending_tokens(self) -> list:
        """
        Get trending tokens from DexScreener with 1H volume focus using custom emojis.
        Returns top 15 trending pairs across supported blockchains.
        """
        CE = Config.CUSTOM_EMOJI_IDS
        try:
            trending_tokens = []
            url = f"{self.base_url}/search/trending"

            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    pairs = data.get('pairs', [])
                    if not data or not pairs:
                        logger.error(
                            f"{CE['cross']['char']} Failed to fetch trending tokens: No pairs found in response.")
                        return []

                    for pair in pairs:
                        chain_id = pair.get('chainId', '')
                        if chain_id not in CryptoBotConfig.BLOCKCHAINS:
                            continue

                        quote_symbol = pair.get('quoteToken', {}).get('symbol', '').upper()
                        if quote_symbol in ['USDT', 'USDC', 'USD']:
                            volume_h1 = float(pair.get('volume', {}).get('h1', 0) or 0)
                            price_change_h1 = float(pair.get('priceChange', {}).get('h1', 0) or 0)

                            if volume_h1 > 5000:
                                pair['chain_name'] = CryptoBotConfig.BLOCKCHAINS[chain_id]['name']
                                trending_tokens.append(pair)
                                logger.info(
                                    f"{CE['rocket']['char']} Trending: {pair.get('baseToken', {}).get('symbol')} - Volume 1H: {volume_h1}"
                                )
                else:
                    logger.error(f"{CE['cross']['char']} Failed to fetch trending tokens, status: {response.status}")

            trending_tokens.sort(key=lambda x: float(x.get('volume', {}).get('h1', 0) or 0), reverse=True)
            return trending_tokens[:15]

        except Exception as e:
            logger.error(f"{CE['cross']['char']} Error fetching trending tokens: {e}")
            return []


class GeckoTerminalAPI:
    def __init__(self):
        self.base_url = "https://api.geckoterminal.com/api/v2"
        self.GECKO_CHAIN_MAP = {
            'ethereum': 'eth', 'bsc': 'bsc', 'solana': 'solana',
            'base': 'base', 'polygon': 'polygon', 'arbitrum': 'arbitrum',
            'tron': 'tron', 'avalanche': 'avax',
        }

    async def get_historical_high_price(self, chain_id: str, pair_address: str) -> Optional[Tuple[float, int]]:
        """
        Retrieves the all-time high (ATH) price and timestamp for a token pair using GeckoTerminal.
        """
        gecko_chain_id = self.GECKO_CHAIN_MAP.get(chain_id.lower())
        if not gecko_chain_id:
            logging.error(f"Chain ID '{chain_id}' is not supported by GeckoTerminal.")
            return None

        url = f"{self.base_url}/networks/{gecko_chain_id}/pools/{pair_address}/ohlcv/hour?limit=500"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if 'data' in data and 'attributes' in data['data']:
                        ohlcv_data = data['data']['attributes']['ohlcv_list']
                        if not ohlcv_data:
                            return None

                        highest_price = 0
                        ath_timestamp = None
                        for record in ohlcv_data:
                            # Data: [timestamp, open, high, low, close, volume]
                            high_price = float(record[2])
                            if high_price > highest_price:
                                highest_price = high_price
                                ath_timestamp = int(record[0])

                        return (highest_price, ath_timestamp)

        except Exception as e:
            logging.error(f"Failed to retrieve historical data from GeckoTerminal: {e}")
            return None

class FastChartGenerator:
    """Generate charts with screenshot capability for trading pairs"""

    @staticmethod
    def generate_coingecko_chart_url(coin_id: str, timeframe: str = '1h') -> str:
        """Generate CoinGecko chart URL for major coins"""
        try:
            days_map = {
                '1h': '1', '2h': '1', '4h': '1', '8h': '1', '12h': '1',
                '1d': '1', '3d': '3', '1w': '7', '2w': '14', '1m': '30'
            }

            days = days_map.get(timeframe, '1')
            chart_url = f"https://www.coingecko.com/en/coins/{coin_id}"

            return chart_url

        except Exception as e:
            logger.error(f"CoinGecko chart URL generation error: {e}")
            return ""

    @staticmethod
    def generate_dexscreener_chart_url(token_data: Dict, timeframe: str = '1h') -> str:
        """Generate DexScreener chart URL for screenshots and embedding"""
        try:
            # Get pair address
            pair_address = token_data.get('pairAddress', '')
            chain_id = token_data.get('chainId', 'ethereum')

            if not pair_address:
                return ""

            base_url = f"https://dexscreener.com/{chain_id}/{pair_address}"

            # Map timeframe for DexScreener
            interval_map = {
                '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
                '1h': '60', '2h': '120', '4h': '240', '8h': '480', '12h': '720',
                '1d': '1D', '3d': '3D', '1w': '1W'
            }

            interval = interval_map.get(timeframe, '60')

            # Return both regular and embed URLs
            regular_url = f"{base_url}?interval={interval}"
            embed_url = f"{base_url}?embed=1&loadChartSettings=0&chartLeftToolbar=0&chartTheme=dark&theme=dark&chartStyle=1&chartType=usd&interval={interval}"

            return regular_url

        except Exception as e:
            logger.error(f"Chart URL generation error: {e}")
            return ""

    @staticmethod
    def generate_dexscreener_embed_url(token_data: Dict, timeframe: str = '1h') -> str:
        """Generate DexScreener embed URL for fast chart display"""
        try:
            # Get pair address
            pair_address = token_data.get('pairAddress', '')
            chain_id = token_data.get('chainId', 'ethereum')

            if not pair_address:
                return ""

            base_url = f"https://dexscreener.com/{chain_id}/{pair_address}"
            embed_params = [
                "embed=1",
                "loadChartSettings=0",
                "chartLeftToolbar=0",
                "chartTheme=dark",
                "theme=dark",
                "chartStyle=1",  # Candlestick style
                "chartType=usd"
            ]

            # Map timeframe
            interval_map = {
                '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
                '1h': '60', '2h': '120', '4h': '240', '8h': '480', '12h': '720',
                '1d': '1D', '3d': '3D', '1w': '1W'
            }

            interval = interval_map.get(timeframe, '60')
            embed_params.append(f"interval={interval}")

            embed_url = f"{base_url}?{'&'.join(embed_params)}"
            return embed_url

        except Exception as e:
            logger.error(f"Embed URL generation error: {e}")
            return ""

    @staticmethod
    def create_fast_chart(token_data: Dict, timeframe: str = '1h') -> str:
        """Create a simple, fast chart with minimal processing - OPTIMIZED"""
        try:
            base_price = float(token_data.get('priceUsd', 1))
            if base_price <= 0:
                base_price = 1.0

            dates = []
            prices = []

            # Only 12 data points for maximum speed
            for i in range(12):
                date = datetime.now() - timedelta(hours=i * 2)  # 2-hour intervals
                dates.append(date)

                # Simple price variation based on market volatility
                variation = (i % 3 - 1) * 0.015  # ±1.5% variation
                price = base_price * (1 + variation)
                prices.append(price)

            dates.reverse()
            prices.reverse()

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates,
                y=prices,
                mode='lines',
                line=dict(color='#00ff88', width=3),
                name="Price",
                fill='tonexty' if len(prices) > 1 else None,
                fillcolor='rgba(0, 255, 136, 0.1)'
            ))

            # Minimal styling for maximum speed
            token_symbol = token_data.get('baseToken', {}).get('symbol', 'TOKEN')

            fig.update_layout(
                title=f"{token_symbol} • {timeframe.upper()}",
                paper_bgcolor='#1a1a1a',
                plot_bgcolor='#1a1a1a',
                font=dict(color='white', size=12),
                height=300,  # Smaller height for speed
                width=600,  # Smaller width for speed
                margin=dict(l=20, r=20, t=40, b=20),
                showlegend=False,
                xaxis=dict(showgrid=False, showticklabels=False),
                yaxis=dict(showgrid=True, gridcolor='#333333')
            )

            img_bytes = fig.to_image(format="png", scale=1, engine="kaleido")
            img_base64 = base64.b64encode(img_bytes).decode()

            return img_base64

        except Exception as e:
            logger.error(f"Fast chart generation error: {e}")
            return ""


class CryptoPriceScannerBot:
    """Main bot class with emoji animations for all users"""
    CUSTOM_EMOJI_IDS = {
        "alarm": {
            "char": "⏰",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6141206421804422655"}]
        },
        "diamond": {
            "char": "🔮",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6141179956215945350"}]
        },
        "chart": {
            "char": "📈",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140812337080179629"}]
        },
        "memo": {
            "char": "📝",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140861398491601488"}]
        },
        "cross": {
            "char": "❌",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140737359836092241"}]
        },
        "idea": {
            "char": "💡",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140764546979076674"}]
        },
        "link": {
            "char": "🔗",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143122866276668612"}]
        },
        "droplet": {
            "char": "💧",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140719492772141505"}]
        },
        "repeat": {
            "char": "🫄",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140832965808101595"}]
        },
        "bank": {

            "char": "🏦",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143439701719127874"}]
        },
        "money": {
            "char": "💰",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140830457547201260"}]
        },
        "trophy": {
            "char": "🏆",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6142917085803583964"}]
        },
        "rocket": {
            "char": "🚀",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143461438548613604"}]
        },
        "magnifier": {
            "char": "🔎",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140757460283039555"}]
        },
        "stopwatch": {
            "char": "⏱️",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140850987490876092"}]
        },
        "chart_down": {
            "char": "📋",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140914578776660570"}]
        },
        "neutral_face": {
            "char": "😐",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6142954215795856741"}]
        },
        "chart_up": {
            "char": "📈",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140949342241954628"}]
        },
        "diamond2": {
            "char": "💎",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143191839156475840"}]
        },
        "warning": {
            "char": "⚠️",
            "entities": [
                {"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143413717166987295"}]
        }
    }

    MAJOR_COINS = {
        "btc": {"name": "Bitcoin", "symbol": "BTC", "coingecko_id": "bitcoin"},
        "eth": {"name": "Ethereum", "symbol": "ETH", "coingecko_id": "ethereum"},
        "bnb": {"name": "Binance Coin", "symbol": "BNB", "coingecko_id": "binancecoin"},
        "sol": {"name": "Solana", "symbol": "SOL", "coingecko_id": "solana"},
        "trx": {"name": "Tron", "symbol": "TRX", "coingecko_id": "tron"},
        "base": {"name": "Base", "symbol": "BASE", "coingecko_id": "base-protocol"},
        "ada": {"name": "Cardano", "symbol": "ADA", "coingecko_id": "cardano"},
        "dot": {"name": "Polkadot", "symbol": "DOT", "coingecko_id": "polkadot"},
        "xrp": {"name": "Ripple", "symbol": "XRP", "coingecko_id": "ripple"},
        "doge": {"name": "Dogecoin", "symbol": "DOGE", "coingecko_id": "dogecoin"},
        "matic": {"name": "Polygon", "symbol": "MATIC", "coingecko_id": "matic-network"},
        "avax": {"name": "Avalanche", "symbol": "AVAX", "coingecko_id": "avalanche-2"},
        "ftm": {"name": "Fantom", "symbol": "FTM", "coingecko_id": "fantom"},
        "atom": {"name": "Cosmos", "symbol": "ATOM", "coingecko_id": "cosmos"},
        "luna": {"name": "Terra Luna", "symbol": "LUNA", "coingecko_id": "terra-luna"},
        "neo": {"name": "NEO", "symbol": "NEO", "coingecko_id": "neo"},
        "icp": {"name": "Internet Computer", "symbol": "ICP", "coingecko_id": "internet-computer"},
        "apt": {"name": "Aptos", "symbol": "APT", "coingecko_id": "aptos"},
        "arb": {"name": "Arbitrum", "symbol": "ARB", "coingecko_id": "arbitrum"},
    }

    BLOCKCHAINS = {
        1: {"name": "Ethereum"},
        56: {"name": "BSC"},
        "solana": {"name": "Solana"},  # pakai string, bukan angka 101
        137: {"name": "Polygon"},
        43114: {"name": "Avalanche"},
        250: {"name": "Fantom"},
        10: {"name": "Optimism"},
        42161: {"name": "Arbitrum"},
        42220: {"name": "Celo"},
        8453: {"name": "Base"},  # fix dari 199 → 8453
        "tron": {"name": "Tron"},  # pakai string
    }

    def is_major_coin(self, token: str) -> bool:
        """Return True if token symbol or name is a major coin."""
        # ✅ PERBAIKAN: Menghapus tanda $ di awal string
        token_clean = token.lstrip('$')
        token_lower = token_clean.lower()

        for key, coin in self.MAJOR_COINS.items():
            if token_lower == key.lower() or token_lower == coin["name"].lower():
                return True
        return False


    def __init__(self):
        self.config = CryptoBotConfig  # pakai class, bukan instance
        self.CUSTOM_EMOJI_IDS = CryptoBotConfig.CUSTOM_EMOJI_IDS
        self.BOT_CTA_LIST = CryptoBotConfig.BOT_CTA_LIST
        self.admin_report_manager = admin_manager
        self.chart_generator = FastChartGenerator()
        self.cmc_api = CoinMarketCapAPI()
        self.session = None


    def get_animated_emoji(self, base_emoji: str, animated_emoji: str) -> str:
        """Return animated emoji for all users - no premium restrictions"""
        return animated_emoji

    async def get_fear_greed_index(self) -> str:
        """Get Fear & Greed Index using custom emojis"""
        CE = Config.CUSTOM_EMOJI_IDS  # Shortcut to custom emojis
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(CryptoBotConfig.FEAR_GREED_API) as response:
                    if response.status != 200:
                        logger.error(f"Fear & Greed API returned status {response.status}")
                        return f"{CE['cross']['char']} **Fear & Greed Index temporarily unavailable**"

                    data = await response.json()
                    fear_data = data['data'][0]

                    value = int(fear_data['value'])
                    classification = fear_data['value_classification']
                    timestamp = int(fear_data['timestamp'])
                    date = datetime.fromtimestamp(timestamp).strftime('%B %d, %Y')

                    # Emoji mapping based on value
                    if value <= 25:
                        emoji = CE['neutral_face']['char']
                        color = CE['cross']['char']
                        sentiment = f"{CE['idea']['char']} **Extreme Fear** - Potential buying opportunity"
                    elif value <= 45:
                        emoji = CE['neutral_face']['char']
                        color = CE['rocket']['char']
                        sentiment = f"{CE['chart_up']['char']} **Fear** - Market cautious"
                    elif value <= 55:
                        emoji = CE['neutral_face']['char']
                        color = CE['diamond']['char']
                        sentiment = f"{CE['chart_up']['char']} **Neutral** - Balanced conditions"
                    elif value <= 75:
                        emoji = CE['chart_up']['char']
                        color = CE['rocket']['char']
                        sentiment = f"{CE['chart_up']['char']} **Greed** - Market optimistic"
                    else:
                        emoji = CE['rocket']['char']
                        color = CE['diamond2']['char']
                        sentiment = f"{CE['warning']['char']} **Extreme Greed** - Consider taking profits"

                    report = (
                        f"{emoji} **Bitcoin Fear & Greed Index**\n\n"
                        f"{color} **Current Score:** {value}/100\n"
                        f"{CE['chart']['char']} **Status:** {classification.title()}\n"
                        f"{CE['alarm']['char']} **Date:** {date}\n\n"
                        f"{sentiment}"
                    )

                    return report

        except Exception as e:
            logger.error(f"Fear & Greed Index error: {e}")
            return f"{CE['cross']['char']} **Fear & Greed Index temporarily unavailable**"

    async def get_custom_report(self, token_id: str, source: str = "dexscreener") -> str:
        """
        Fetch custom report for a token.
        token_id: contract address (dex) or coingecko_id (coingecko)
        source: 'dexscreener' or 'coingecko'
        """
        reports_file = "promo.json"  # changed file name
        if not os.path.exists(reports_file):
            return ""

        try:
            with open(reports_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return ""

        # promo.json structure example:
        # {
        #   "btc": "Custom bullish report text",
        #   "5XoWDw...": "Custom report for a token"
        # }
        token_key = token_id.lower()
        report = data.get(token_key)
        return report or ""

    async def search_token_price(self, query: str) -> Tuple[str, str, Optional[str]]:
        CE = Config.CUSTOM_EMOJI_IDS
        query_lower = query.lower().strip()

        # =========================
        # Check major coins (CoinGecko)
        # =========================
        major_coin_data = None
        for key, coin in self.MAJOR_COINS.items():
            if query_lower in [coin["symbol"].lower(), coin["name"].lower()]:
                major_coin_data = coin
                break

        if self.is_major_coin(query_lower):
            coingecko_id = major_coin_data["coingecko_id"]
            detected_chain = "ETHEREUM"  # Asumsi major coins ada di ETH untuk tracking

            async with aiohttp.ClientSession() as session:
                url = (
                    f"https://api.coingecko.com/api/v3/coins/{coingecko_id}"
                    "?localization=false&tickers=false&market_data=true&community_data=false"
                    "&developer_data=false&sparkline=false"
                )
                async with session.get(url) as resp:
                    if resp.status != 200:
                        # ✅ PERBAIKAN: Mengembalikan tuple saat gagal
                        return (f"{CE['cross']['char']} Could not fetch price for {query}", query, None)
                    data = await resp.json()

            market_data = data.get("market_data", {})
            price = market_data.get("current_price", {}).get("usd", 0)
            change_24h = market_data.get("price_change_percentage_24h", 0)
            market_cap = market_data.get("market_cap", {}).get("usd", 0)
            volume_24h = market_data.get("total_volume", {}).get("usd", 0)
            ath = market_data.get("ath", {}).get("usd", 0)
            rank = data.get("market_cap_rank", "N/A")
            name = major_coin_data["name"]
            symbol = major_coin_data["symbol"]

            # --- Price formatting ---
            if price >= 1000:
                price_display = f"${price:,.0f}"
            elif price >= 1:
                price_display = f"${price:,.2f}"
            elif price >= 0.01:
                price_display = f"${price:.4f}"
            else:
                price_display = f"${price:.8f}"

            # --- Market cap formatting ---
            if market_cap >= 1e12:
                mc_display = f"${market_cap / 1e12:.2f}T"
            elif market_cap >= 1e9:
                mc_display = f"${market_cap / 1e9:.2f}B"
            elif market_cap >= 1e6:
                mc_display = f"${market_cap / 1e6:.2f}M"
            else:
                mc_display = f"${market_cap:,.0f}"

            # --- Volume formatting ---
            if volume_24h >= 1e9:
                vol_display = f"${volume_24h / 1e9:.2f}B"
            elif volume_24h >= 1e6:
                vol_display = f"${volume_24h / 1e6:.2f}M"
            elif volume_24h >= 1e3:
                vol_display = f"${volume_24h / 1e3:.2f}K"
            else:
                vol_display = f"${volume_24h:.2f}"

            # --- Trend emoji ---
            if change_24h >= 10:
                trend_emoji = CE['rocket']['char'] + CE['repeat']['char']
            elif change_24h >= 5:
                trend_emoji = CE['chart_up']['char'] + CE['diamond']['char']
            elif change_24h >= 0:
                trend_emoji = CE['chart_up']['char']
            else:
                trend_emoji = CE['chart_down']['char']

            # --- Track scan ---
            from stats_manager import track_scan
            await track_scan(token_address=None, chain=detected_chain)

            # --- Build report ---
            report = (
                f"{trend_emoji} [{name}](https://www.coingecko.com/en/coins/{coingecko_id}) (${symbol})\n"
                f"├ CoinGecko ID: {coingecko_id}\n"
                f"└ Rank: #{rank}\n\n"
                f"📊 Token Stats\n"
                f" ├ USD: {price_display} ({change_24h:+.2f}%)\n"
                f" ├ MC: {mc_display}\n"
                f" ├ Vol: {vol_display}\n"
                f" └ ATH: ${ath:,.2f}\n\n"
            )

            # --- Links ---
            report += "🔗 Links:\n"
            report += f" • [CoinGecko](https://www.coingecko.com/en/coins/{coingecko_id})\n"
            report += f" • [CoinMarketCap](https://coinmarketcap.com/currencies/{coingecko_id}/)\n"

            # --- Random Bot CTA ---
            bot_name, bot_text, bot_url = random.choice(self.BOT_CTA_LIST)
            report += f"\n[{bot_text}]({bot_url.format(addr=coingecko_id)})\n"

            # ✅ PERBAIKAN: Mengembalikan tuple yang benar
            return (report, query, detected_chain)

        # =========================
        # Fallback DexScreener
        # =========================
        else:
            async with DexScreenerAPI() as api:
                results = await api.search_token(query)
                if not results:
                    # ✅ PERBAIKAN: Mengembalikan tuple saat tidak ditemukan
                    return (f"{CE['cross']['char']} No results found for `{query}`", query, None)

                pair = results[0]
                base_token = pair.get('baseToken') or {}
                symbol = base_token.get('symbol', 'Unknown')
                name = base_token.get('name', 'Unknown')
                contract = base_token.get('address', 'N/A')
                chain_id = pair.get('chainId', 'unknown')
                chain_info = CryptoBotConfig.BLOCKCHAINS.get(chain_id, {'name': '❓ Unknown'})
                detected_chain = chain_id  # Tetapkan detected_chain di sini

                price = float(pair.get("priceUsd") or 0)
                change_24h = float((pair.get("priceChange") or {}).get("h24") or 0)
                change_1h = float((pair.get("priceChange") or {}).get("h1") or 0)
                mc = float(pair.get("fdv") or 0)
                volume_24h = float((pair.get("volume") or {}).get("h24") or 0)
                lp = float((pair.get("liquidity") or {}).get("usd") or 0)
                age_days = pair.get("ageDays", 0)
                txns_h1 = pair.get("txns", {}).get("h1", {})
                buys_1h = txns_h1.get("buys", 0)
                sells_1h = txns_h1.get("sells", 0)
                views = pair.get("txns", {}).get("h24", {}).get("buys", 0) + pair.get("txns", {}).get("h24", {}).get(
                    "sells", 0)

                def fmt_num(n):
                    if n >= 1e9: return f"{n / 1e9:.2f}B"
                    if n >= 1e6: return f"{n / 1e6:.2f}M"
                    if n >= 1e3: return f"{n / 1e3:.2f}K"
                    return f"{n:,.2f}"

                price_display = f"${price:.8f}" if price < 1 else f"${price:,.2f}"

                # ✅ LOGIKA LENGKAP UNTUK MENGHITUNG ATH MARKETCAP & STATUS
                geckoterminal_api = GeckoTerminalAPI()

                pair_address_dex = pair.get('pairAddress')
                ath_data = None
                if pair_address_dex:
                    ath_data = await geckoterminal_api.get_historical_high_price(chain_id, pair_address_dex)

                ath_mcap = None
                percent_from_ath = None
                time_since_ath = None

                if ath_data is not None and price > 0:
                    ath_price, ath_timestamp = ath_data
                    ath_mcap = (ath_price / price) * mc

                    if ath_mcap > 0:
                        percent_from_ath = (mc - ath_mcap) / ath_mcap * 100

                    if ath_timestamp:
                        ath_datetime = datetime.fromtimestamp(ath_timestamp)
                        time_delta = datetime.now() - ath_datetime

                        if time_delta.days > 0:
                            time_since_ath = f"{time_delta.days}d"
                        elif time_delta.seconds > 3600:
                            hours = time_delta.seconds // 3600
                            time_since_ath = f"{hours}h"
                        else:
                            minutes = time_delta.seconds // 60
                            time_since_ath = f"{minutes}m"

                # --- Build report ---
                report = (
                    f"🔸 [{name}](https://dexscreener.com/{chain_id}/{pair.get('pairAddress')}) (${symbol})\n"
                    f"├ `{contract}`\n"
                    f"└ #{chain_info['name']} || 👁️{views}\n\n"
                    f"📊 Token Stats\n"
                    f" ├ `USD`:  {price_display} ({change_24h:+.0f}%|24h)\n"
                    f" ├ `MC`:   ${fmt_num(mc)}\n"
                    f" ├ `Vol`:  ${fmt_num(volume_24h)}\n"
                    f" ├ `LP`:   ${fmt_num(lp)}\n"
                    f" ├ `1H`:   {change_1h:+.2f}% 🅑 {buys_1h} Ⓢ {sells_1h}\n"
                )

                # Tambahkan ATH Marketcap dengan format baru
                if ath_mcap is not None and percent_from_ath is not None and time_since_ath is not None:
                    report += f" └ `ATH`: ${fmt_num(ath_mcap)} ({percent_from_ath:+.0f}% / {time_since_ath})\n\n"
                else:
                    report += f" └ `ATH`: N/A\n\n"

                # --- Links ---
                links = await get_token_links(contract, chain=chain_id)
                link_items = []
                if links.get("website"): link_items.append(f"[WEB]({links['website']})")
                if links.get("twitter"): link_items.append(f"[𝕏]({links['twitter']})")
                if links.get("telegram"): link_items.append(f"[TG]({links['telegram']})")
                if links.get("discord"): link_items.append(f"[DC]({links['discord']})")
                if links.get("token_explorer"): link_items.append(f"[EXP]({links['token_explorer']})")

                if contract and chain_id:
                    dex_link = f"https://dexscreener.com/{chain_id}/{contract}"
                    link_items.append(f"[DEX]({dex_link})")

                for i, url in enumerate(links.get("pair_explorers", []), start=1):
                    link_items.append(f"[PXP]({url})")

                if link_items:
                    report += f"🔗 Links\n└ " + " • ".join(link_items) + "\n\n"

                # --- Security Section ---
                if contract and chain_id:
                    async with aiohttp.ClientSession() as session:
                        sec_info = await get_security_info(session, contract, chain_id)
                        if sec_info:
                            report += sec_info + "\n\n"

                # --- Bot trading links ---
                bot_trading_links = [
                    f"[{bot_name}]({url.format(addr=contract)})"
                    for bot_name, url in SOL_BOT_TRADING
                ]
                report += "🤖\n"
                report += f"└ {' • '.join(bot_trading_links)}\n"

                # --- Random CTA ---
                bot_name, bot_text, bot_url = random.choice(self.BOT_CTA_LIST)
                report += f"\n[{bot_text}]({bot_url.format(addr=contract)})\n"

        # --- Global promos ---
        from promo_manager import get_custom_report
        global_promos = await get_custom_report()
        if global_promos:
            report += f"\n🔔 PROMO:\n{global_promos}\n"

        # ✅ PERBAIKAN: Mengembalikan tuple yang benar
        return (report, query, detected_chain)

    # di dalam class Bot kamu
    async def get_chart(self, query: str, timeframe: str = "1h") -> tuple[str, str, str]:
        """
        Generate chart:
        - Major coins: caption only (no screenshot)
        - Non-major (DexScreener): chart screenshot + caption
        Return: (caption, chart_type, chart_file_path)
        """
        CE = Config.CUSTOM_EMOJI_IDS
        query_lower = query.lower().strip()

        try:
            # --- Major coins (no screenshot) ---
            for coin_key, coin_info in CryptoBotConfig.MAJOR_COINS.items():
                if query_lower == coin_key or query_lower == coin_info["symbol"].lower():
                    major_coin_data = await self.cmc_api.get_major_coin_data(coin_info["symbol"])
                    if not major_coin_data:
                        break  # ← NOTE: ini bikin keluar loop tapi lanjut ke DexScreener, bukan return

                    symbol = major_coin_data.get("symbol", coin_info["symbol"])
                    name = major_coin_data.get("name", coin_key.upper())
                    price = major_coin_data.get("price", 0.0)
                    change_24h = major_coin_data.get("percent_change_24h", 0.0)
                    rank = major_coin_data.get("rank", "N/A")

                    price_display = f"${price:,.2f}" if price >= 1 else f"${price:.6f}"
                    coingecko_id = name.lower().replace(" ", "-")
                    chart_url = self.chart_generator.generate_coingecko_chart_url(coingecko_id, timeframe)

                    caption = (
                        f"{CE['chart']['char']} **{name} ({symbol}) Chart — {timeframe.upper()}**\n\n"
                        f"{CE['money']['char']} **Price:** {price_display}\n"
                        f"{CE['chart_up']['char']} **24H:** {'+' if change_24h >= 0 else ''}{change_24h:.2f}%\n"
                        f"{CE['trophy']['char']} **Rank:** #{rank}\n\n"
                        f"{CE['chart_up']['char']} **Interactive Chart:** [Open on CoinGecko]({chart_url})\n"
                    )
                    return caption, "MAJOR_COIN_CHART", ""

            # --- DexScreener fallback (with screenshot) ---
            async with DexScreenerAPI() as api:
                results = await api.search_token(query)
                if not results:
                    return f"{CE['cross']['char']} **No chart data found for:** `{query}`", "NO_DATA", ""

                token = results[0]
                base_token = token.get("baseToken", {})
                symbol = base_token.get("symbol", "TOKEN")
                name = base_token.get("name", symbol)
                price = float(token.get("priceUsd") or 0.0)
                price_change_1h = float(token.get("priceChange", {}).get("h1") or 0.0)
                price_change_24h = float(token.get("priceChange", {}).get("h24") or 0.0)
                chain_id = token.get("chainId", "unknown")
                chain_info = CryptoBotConfig.BLOCKCHAINS.get(chain_id, {"name": "❓ Unknown"})
                contract = base_token.get("address", "N/A")
                pair_addr = token.get("pairAddress") or token.get("pairAddressV2") or token.get("pairAddressV3")

                if not pair_addr:
                    return f"{CE['warning']['char']} **No trading pair found for:** `{query}`", "NO_DATA", ""

                # Format price
                if price < 0.000001:
                    price_display = f"${price:.10f}"
                elif price < 0.01:
                    price_display = f"${price:.6f}"
                else:
                    price_display = f"${price:.4f}"

                from chart_renderer import ChartRenderer
                ds_url = ChartRenderer.build_dexscreener_url(
                    chain_id=chain_id,
                    pair_address=pair_addr,
                    timeframe=timeframe
                )

                # Screenshot chart
                file_hint = f"{symbol}_{chain_id}_{timeframe}"
                output_path = f"charts/{file_hint}.png"
                chart_path = await ChartRenderer.screenshot_chart(ds_url, output_path)

                if not chart_path:
                    return f"{CE['cross']['char']} **Failed to capture chart for:** `{symbol}`", "ERROR", ""

                caption = (
                    f"{CE['chart']['char']} **{symbol} Chart — {timeframe.upper()}** • {chain_info['name']}\n\n"
                    f"{CE['money']['char']} **Price:** {price_display}\n"
                    f"{CE['chart_down']['char']} **1H:** {'+' if price_change_1h >= 0 else ''}{price_change_1h:.2f}%\n"
                    f"{CE['chart_up']['char']} **24H:** {'+' if price_change_24h >= 0 else ''}{price_change_24h:.2f}%\n"
                    f"{CE['memo']['char']} **Contract:** `{contract}`\n\n"
                    f"{CE['chart_up']['char']} **Interactive Chart:** [Open on DexScreener]({ds_url})\n"
                )

                return caption, "DEX_CHART", chart_path

        except Exception as e:
            logger.error(f"Chart generation error: {e}", exc_info=True)
            return f"{CE['cross']['char']} **Chart error:** {str(e)}", "ERROR", ""


# Command handlers
# Ganti fungsi handle_price_command Anda
# In your main.py file, replace the handle_price_command function

# Di dalam file main.py, ganti fungsi handle_price_command

async def handle_price_command(query: str) -> Tuple[str, str, Optional[str]]:
    """
    Handle /p command with custom emojis.
    Returns the report text, token address, and detected chain_id.
    """
    CE = Config.CUSTOM_EMOJI_IDS
    query = query.strip().lstrip("$")

    if not query:
        return (
            f"{CE['warning']['char']} **Please provide a token symbol, name, or contract address.**",
            "",
            None,
        )

    try:
        async with DexScreenerAPI() as dex_api:
            bot = CryptoPriceScannerBot()
            detected_chain = None
            pair_data = None

            # 🚀 Step 1: Kalau query berupa link Dexscreener
            m = re.match(r"^https?://dexscreener\.com/(\w+)/([A-Za-z0-9]+)$", query)
            if m:
                chain_from_url, id_from_url = m.group(1).lower(), m.group(2)
                query = id_from_url

                # coba sebagai pairId dulu
                try:
                    pair_data = await dex_api.get_pair_by_id(chain_from_url, id_from_url)
                    if pair_data and pair_data.get("pairs"):
                        detected_chain = chain_from_url
                        query = pair_data["pairs"][0]["baseToken"]["address"]
                except Exception as e:
                    logger.warning(f"DexScreener get_pair_by_id failed: {e}")

                # fallback → contract address
                if not detected_chain:
                    try:
                        pair_data = await dex_api.get_pair_info(id_from_url, chain_from_url)
                        if pair_data:
                            detected_chain = chain_from_url
                            query = pair_data.get("baseToken", {}).get("address", query)
                    except Exception as e:
                        logger.warning(f"DexScreener get_pair_info failed: {e}")

            # 🚀 Step 2: Kalau query bisa jadi PairId
            if not detected_chain and re.match(r"^[A-Za-z0-9]{32,44}$", query):
                for chain_id in ["solana", "bsc", "ethereum", "base", "tron"]:
                    try:
                        pair_data = await dex_api.get_pair_by_id(chain_id, query)
                        if pair_data and pair_data.get("pairs"):
                            detected_chain = chain_id
                            query = pair_data["pairs"][0]["baseToken"]["address"]
                            break
                    except Exception as e:
                        logging.error(f"Error fetching pair {query} on {chain_id}: {e}")

            # 🚀 Step 3: Kalau query contract address
            if not detected_chain and re.match(r"^(0x[a-fA-F0-9]{40}|T[a-zA-Z0-9]{33})$", query):
                for chain_id in ["ethereum", "bsc", "base", "solana", "tron"]:
                    try:
                        pair_data = await dex_api.get_pair_info(query, chain_id)
                        if not pair_data:
                            # fallback ke /search → pilih liquidity terbesar
                            search_data = await dex_api.search_token(query)
                            if search_data:
                                pair_data = max(search_data, key=lambda p: p.get("liquidity", {}).get("usd", 0))
                        if pair_data:
                            detected_chain = pair_data.get("chainId", chain_id)
                            query = pair_data.get("baseToken", {}).get("address", query)
                            break
                    except Exception as e:
                        logging.error(f"Error checking contract {query} on {chain_id}: {e}")

            # 🚀 Step 4: Jalankan bot report
            bot_result = await bot.search_token_price(query)

            if isinstance(bot_result, tuple):
                if len(bot_result) == 3:
                    result, final_query, detected_chain_from_bot = bot_result

                    if not detected_chain:
                        if detected_chain_from_bot:
                            detected_chain = detected_chain_from_bot
                        else:
                            detected_chain = "UNKNOWN"

                elif len(bot_result) == 2:
                    result, final_query = bot_result
                    detected_chain = detected_chain or "UNKNOWN"
                else:
                    result = f"{CE['cross']['char']} **Invalid data format: Tuple length {len(bot_result)}**"
                    final_query = query
                    detected_chain = None
            else:
                result = f"{CE['cross']['char']} **Invalid data format: {type(bot_result).__name__}**"
                final_query = query
                detected_chain = None

            logging.debug(f"[PRICE_CMD] final_chain={detected_chain}, query={query}")
            return result, final_query, detected_chain

    except Exception as e:
        logging.error(
            f"{CE['cross']['char']} Price command error for '{query}': {e}",
            exc_info=True,
        )
        return f"{CE['cross']['char']} **Error fetching price for:** `{query}`", "", None




async def handle_chart_command(query: str, timeframe: str = "1h") -> Tuple[str, str, str]:
    """
    Handle /c command:
    - Calls get_chart() from CryptoPriceScannerBot
    - Returns (caption, chart_type, chart_file_path) where chart_file_path sudah terkompresi
    """
    CE = Config.CUSTOM_EMOJI_IDS  # shortcut for custom emojis
    query = query.strip()

    if not query:
        return (
            f"{CE['warning']['char']} **Please provide a token symbol, name, or contract address.**",
            "NO_QUERY",
            ""
        )

    try:
        # ✅ PERBAIKAN: Inisialisasi bot tanpa `async with`
        bot = CryptoPriceScannerBot()

        # Generate chart (caption, chart_type, chart_file_path)
        caption, chart_type, chart_file_path = await bot.get_chart(query, timeframe)

        # Kalau chart berhasil, kompres dulu sebelum return
        if chart_file_path and os.path.exists(chart_file_path):
            try:
                from chart_renderer import compress_image  # taruh helper compress di chart_renderer.py
                chart_file_path = compress_image(chart_file_path)
            except Exception as e:
                logger.warning(f"Chart compression failed: {e}")

        return caption, chart_type, chart_file_path

    except Exception as e:
        logger.error(f"{CE['cross']['char']} Chart command error for '{query}': {e}", exc_info=True)
        return (
            f"{CE['cross']['char']} **Chart generation failed for:** `{query}`",
            "ERROR",
            ""
        )


async def handle_chart_button(token: str, timeframe: str, query, context):
    """Handle chart button callbacks (same as /c command)."""
    CE = Config.CUSTOM_EMOJI_IDS

    loading_msg = await query.message.reply_text(
        f"{CE['chart']['char']} **Generating Chart**\n"
        f"{CE['magnifier']['char']} **Token:** `{escape_markdown(token, version=1)}`\n"
        f"{CE['stopwatch']['char']} **Timeframe:** `{escape_markdown(timeframe, version=1)}`\n"
        f"{CE['repeat']['char']} **Processing...**",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        # 🔑 panggil handle_chart_command (sudah auto compress di sana)
        caption, chart_type, chart_path = await handle_chart_command(token, timeframe)

        keyboard = [
            [
                InlineKeyboardButton(f"{CE['chart']['char']} 1m", callback_data=f"chart_{token}_1m"),
                InlineKeyboardButton(f"{CE['chart']['char']} 5m", callback_data=f"chart_{token}_5m"),
                InlineKeyboardButton(f"{CE['chart']['char']} 15m", callback_data=f"chart_{token}_15m"),
            ],
            [
                InlineKeyboardButton(f"{CE['chart']['char']} 30m", callback_data=f"chart_{token}_30m"),
                InlineKeyboardButton(f"{CE['chart']['char']} 1h", callback_data=f"chart_{token}_1h"),
                InlineKeyboardButton(f"{CE['chart']['char']} 4h", callback_data=f"chart_{token}_4h"),
            ],
            [
                InlineKeyboardButton(f"{CE['chart']['char']} 1d", callback_data=f"chart_{token}_1d"),
                InlineKeyboardButton(f"{CE['chart']['char']} 1w", callback_data=f"chart_{token}_1w"),
            ],
            [
                #InlineKeyboardButton(f"{CE['money']['char']} Price Info", callback_data=f"price_{token}"),
                InlineKeyboardButton(f"{CE['bank']['char']} Main Menu", callback_data="start"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if chart_type in ["MAJOR_COIN_CHART", "NO_DATA", "ERROR"]:
            await loading_msg.edit_text(
                caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )


        elif chart_path:  # ✅ chart_path sudah hasil kompres dari handle_chart_command

            await loading_msg.delete()

            with open(chart_path, "rb") as img:

                await context.bot.send_photo(

                    chat_id=query.message.chat_id,

                    photo=img,

                    caption=caption,

                    parse_mode=ParseMode.MARKDOWN,

                    reply_markup=reply_markup,

                    read_timeout=60,

                    write_timeout=60

                )

        else:
            await loading_msg.edit_text(
                caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Chart button error: {e}", exc_info=True)
        await loading_msg.edit_text(
            f"{CE['cross']['char']} **Chart Loading Failed**\n\n"
            f"Token: `{escape_markdown(token, version=1)}`\n"
            f"{CE['idea']['char']} Try command: `/c {token} {timeframe}`",
            parse_mode=ParseMode.MARKDOWN
        )




async def handle_fear_index_command() -> str:
    """Handle /fearindex command with custom emojis and error handling"""
    CE = Config.CUSTOM_EMOJI_IDS  # shortcut for custom emojis
    try:
        bot = CryptoPriceScannerBot()
        report = await bot.get_fear_greed_index()
        return report
    except Exception as e:
        logger.error(f"{CE['cross']['char']} Fear & Greed Index command error: {e}", exc_info=True)
        return f"{CE['cross']['char']} **Unable to fetch Fear & Greed Index at the moment.**"



#async def handle_fed_command() -> str:
#    """Handle /fed command"""
#    return """🏛️ **Federal Reserve Watch**
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#📊 **Current Rate:** 5.25% - 5.50%
#📅 **Next FOMC:** December 17-18, 2024
#📈 **Probability:**
#   • Hold (5.25-5.50%): 65%
#   • Cut to 5.00-5.25%: 35%
#📰 **Last Update:** Fed maintains current rates"""


async def handle_trending_command() -> str:
    """Handle /dext /ave command"""
    # If you still want to get trending tokens, you can keep it
    bot = CryptoPriceScannerBot()
    trending = await bot.get_trending_tokens()  # optional, if you want to include it

    # Return the website link (can include trending info if needed)
    return f"🌐 Check trending tokens here: https://fourtis.io/\n\nTrending tokens: {trending}"


# Demo function
async def demo_bot():
    """Demo function to test all bot features"""
    print("🤖 Crypto Price & Scanner Bot Demo\n")

    print("Testing contract address: AdVfQkuFeDNLgkzgpcdq9vCf8yf9KBV4KYASCVMxbonk")
    price_report = await handle_price_command("AdVfQkuFeDNLgkzgpcdq9vCf8yf9KBV4KYASCVMxbonk")
    print(price_report)
    print("\n" + "=" * 50 + "\n")

    print("Testing major coin: BNB")
    bnb_report = await handle_price_command("BNB")
    print(bnb_report)
    print("\n" + "=" * 50 + "\n")

    print("Testing /c command...")
    chart_caption, chart_data = await handle_chart_command("ethereum", "1h")
    print(chart_caption)
    if chart_data:
        print("📊 Chart generated successfully!")
    print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(demo_bot())