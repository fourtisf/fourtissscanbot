import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _env_int(name: str, default: int) -> int:
    """int(os.getenv(...)) mentah crash saat variabel di-set tapi kosong
    (mis. 'PORT=' di .env) — bot gagal start hanya karena satu baris kosong."""
    value = os.getenv(name)
    try:
        return int(value) if value and value.strip() else default
    except ValueError:
        return default


class Config:
    """Simplified configuration for the rebuilt crypto bot"""

    # Telegram Bot Token (get from @BotFather)
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

    CUSTOM_EMOJI_IDS = {
        "alarm": {
            "char": "⏰",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6141206421804422655"}]
        },
        "diamond": {
            "char": "🔮",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6141179956215945350"}]
        },
        "chart": {
            "char": "📈",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140812337080179629"}]
        },
        "memo": {
            "char": "📝",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140861398491601488"}]
        },
        "cross": {
            "char": "❌",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140737359836092241"}]
        },
        "idea": {
            "char": "💡",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140764546979076674"}]
        },
        "link": {
            "char": "🔗",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143122866276668612"}]
        },
        "droplet": {
            "char": "💧",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140719492772141505"}]
        },
        "repeat": {
            "char": "🫄",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140832965808101595"}]
        },
        "bank": {
            "char": "🏦",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143439701719127874"}]
        },
        "money": {
            "char": "💰",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140830457547201260"}]
        },
        "trophy": {
            "char": "🏆",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6142917085803583964"}]
        },
        "rocket": {
            "char": "🚀",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143461438548613604"}]
        },
        "magnifier": {
            "char": "🔎",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140757460283039555"}]
        },
        "stopwatch": {
            "char": "⏱️",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140850987490876092"}]
        },
        "chart_down": {
            "char": "📋",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140914578776660570"}]
        },
        "neutral_face": {
            "char": "😐",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6142954215795856741"}]
        },
        "chart_up": {
            "char": "📈",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6140949342241954628"}]
        },
        "diamond2": {
            "char": "💎",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143191839156475840"}]
        },
        "warning": {
            "char": "⚠️",
            "entities": [{"offset": 0, "length": 1, "type": "custom_emoji", "custom_emoji_id": "6143413717166987295"}]
        }
    }

    MAJOR_COINS = {
        "btc": {"name": "Bitcoin", "symbol": "BTC", "coingecko_id": "bitcoin"},
        "eth": {"name": "Ethereum", "symbol": "ETH", "coingecko_id": "ethereum"},
        "bnb": {"name": "BNB", "symbol": "BNB", "coingecko_id": "binancecoin"},
        "sol": {"name": "Solana", "symbol": "SOL", "coingecko_id": "solana"},
        "trx": {"name": "TRON", "symbol": "TRX", "coingecko_id": "tron"},
        "base": {"name": "Base", "symbol": "BASE", "coingecko_id": "base"}  # optional
    }

    # Bot Settings
    MAX_TOKENS_PER_CHAIN = _env_int('MAX_TOKENS_PER_CHAIN', 3)
    DEFAULT_TIMEFRAME = os.getenv('DEFAULT_TIMEFRAME', '1h')
    CHART_WIDTH = _env_int('CHART_WIDTH', 1000)
    CHART_HEIGHT = _env_int('CHART_HEIGHT', 600)

    # Rate Limiting
    REQUESTS_PER_MINUTE = _env_int('REQUESTS_PER_MINUTE', 60)
    CACHE_DURATION = _env_int('CACHE_DURATION', 300)  # 5 minutes

    # Webhook Settings (for production)
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    PORT = _env_int('PORT', 8443)


# Animated emojis for ALL users (no premium restrictions)
ANIMATED_EMOJIS = {
    'fire': '💎',
    'up': '✨',
    'down': '💥',
    'crown': '💠',
    'rocket': '💫',
    'search': '💎',
    'loading': '🔄',
    'chart': '📊',
    'money': '💰',
    'success': '✅',
    'error': '❌',
    'warning': '⚠️'
}

SOL_BOT_TRADING = [
    ("AXI", "https://axiom.trade/@fourtis"),
    ("TRO", "https://t.me/paris_trojanbot?start=r-charliefourtis"),
    ("PHO", "https://photon-sol.tinyastro.io/@fourtis"),
    ("GM",  "https://gmgn.ai/r/25JyIYly"),
    ("BLO", "https://t.me/BloomSolana_bot?start=ref_fourtis"),
    ("MAE", "https://t.me/maestro?start=r-charliefourtis"),
    ("BAN", "https://t.me/BananaGun_bot?start=ref_fourtisbot"),
]


# Regular emojis (fallback)
REGULAR_EMOJIS = {
    'fire': '🔥',
    'up': '🟢',
    'down': '🔴',
    'crown': '👑',
    'rocket': '🚀',
    'search': '🔍',
    'loading': '🔄',
    'chart': '📊',
    'money': '💰',
    'success': '✅',
    'error': '❌',
    'warning': '⚠️'
}



# Supported blockchain networks (5 main chains only)
SUPPORTED_CHAINS = {
    'ethereum': {
        'name': 'Ethereum',
        'symbol': 'ETH',
        'emoji': '🔷',
        'chain_id': 'ethereum',
        'explorer': 'https://etherscan.io'
    },
    'bsc': {
        'name': 'BNB Smart Chain',
        'symbol': 'BNB',
        'emoji': '🟡',
        'chain_id': 'bsc',
        'explorer': 'https://bscscan.com'
    },
    'solana': {
        'name': 'Solana',
        'symbol': 'SOL',
        'emoji': '🟣',
        'chain_id': 'solana',
        'explorer': 'https://solscan.io'
    },
    'base': {
        'name': 'Base',
        'symbol': 'BASE',
        'emoji': '🔵',
        'chain_id': 'base',
        'explorer': 'https://basescan.org'
    },
    'tron': {
        'name': 'Tron',
        'symbol': 'TRX',
        'emoji': '🔴',
        'chain_id': 'tron',
        'explorer': 'https://tronscan.org'
    }
}

# DexScreener API Configuration
DEXSCREENER_CONFIG = {
    'base_url': 'https://api.dexscreener.com/latest',
    'timeout': 15,  # Fast timeout for quick responses
    'max_retries': 2
}

# Chart configuration for professional styling
CHART_CONFIG = {
    'background_color': '#1a1a1a',
    'grid_color': 'rgba(128, 128, 128, 0.2)',
    'up_color': '#00ff88',
    'down_color': '#ff4444',
    'volume_color': 'rgba(128, 128, 128, 0.3)',
    'text_color': 'white'
}
