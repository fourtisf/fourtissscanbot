import asyncio
import json
import logging
import asyncio
from telegram.error import BadRequest
from datetime import datetime, timezone, time as dt_time
from globals import admin_manager, ADMIN_IDS
from leaderboard import leaderboard_command
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, Application, CommandHandler, CallbackQueryHandler, MessageHandler)
from telegram.ext import ContextTypes, filters
from telegram.constants import ParseMode
from admin_report_manager import AdminReportManager
from pnl_manager import scan_command, pnl_command, list_scans_command, save_scan_row, fetch_current_mcap, process_and_save_scan
from promo_manager import add_report, reset_reports
import io
from telegram.helpers import escape_markdown
import base64
from main import (
    handle_price_command, handle_chart_command,
    handle_fear_index_command, CryptoBotConfig, handle_chart_button
)
from main import CryptoPriceScannerBot
from stats_manager import (
    track_chat, track_scan, get_status_message, stats, save_stats, load_stats, reset_daily_stats
)
import re
import telegram
from chart_renderer import compress_image
import os
from dotenv import load_dotenv
from telegram.request import HTTPXRequest
from bot_config import Config
from chart_renderer import ChartRenderer
from utils import format_custom_emoji

CE = Config.CUSTOM_EMOJI_IDS


def emoji(name: str, default: str = '💠') -> str:
    return CE.get(name, {}).get('char', default)


# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ADMINS = [1322401802, 7176469093]  # replace with your Telegram IDs
admin_report_manager = AdminReportManager(admin_ids=[1322401802, 7176469093])


def escape_md(text: str) -> str:
    """Escape text for Telegram Markdown parsing."""
    if not text:
        return ""
    escape_chars = r"_*[]()~`>#+-=|{}.!$"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def escape_all_markdown_v2(text: str) -> str:
    """
    Escapes all characters that have special meaning in MarkdownV2.
    """
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def get_current_time_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")  # UTC-5


class TelegramCryptoBot:
    """Telegram bot implementation with emoji animations for all users"""

    def __init__(self, token: str, admin_ids: list | None = None):
        self.token = token
        self.config = CryptoBotConfig()

        # Load stats dari file JSON (mengisi module-level stats)
        load_stats()

        # Build application
        self.application = ApplicationBuilder().token(token).request(
            HTTPXRequest(
                connection_pool_size=10,
                read_timeout=20.0,
                connect_timeout=20.0,
                write_timeout=20.0
            )
        ).build()
        self.admin_report_manager = AdminReportManager(admin_ids=[1322401802, 7176469093])
        # Setup command & message handlers
        self.setup_handlers()

        # === JOBS ===

        # 1️⃣ Broadcast stats ke semua user/group tiap 2 menit (testing)
        self.application.job_queue.run_repeating(
            self.broadcast_stats_job,
            interval=43200,  # 2 menit testing, ganti 43200 = 12 jam produksi
            first=10,
            name="broadcast_stats_job"
        )

        # 2️⃣ Save stats rutin tiap 1 menit
        async def _save_stats_job(ctx: ContextTypes.DEFAULT_TYPE):
            # Jalankan save_stats di thread pool agar tidak block loop
            await asyncio.to_thread(save_stats)
            logger.info("[JOB] Saved stats (background)")

        self.application.job_queue.run_repeating(
            _save_stats_job,
            interval=60,
            first=60,
            name="save_stats_job"
        )

        # 3️⃣ Reset harian jam 00:00 UTC
        async def _reset_daily_stats_job(ctx: ContextTypes.DEFAULT_TYPE):
            await asyncio.to_thread(reset_daily_stats)
            logger.info("[JOB] Daily stats reset")

        self.application.job_queue.run_daily(
            _reset_daily_stats_job,
            time=dt_time(hour=0, minute=0, tzinfo=timezone.utc),
            name="reset_daily_stats_job"
        )

    def emoji(self, name, default='💠'):
        return self.config.CUSTOM_EMOJI_IDS.get(name, {}).get('char', default)

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

    # Initialize AdminReportManager with your admin Telegram IDs
    ##admin_report_manager = AdminReportManager(admin_ids=admin_ids)
    # ADMINS = [123456789, 987654321]

    def setup_handlers(self):
        """Setup command and callback handlers"""
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        # telegram_bot.py (inside TelegramCryptoBot.__init__ or setup_handlers)
        self.admin_report_manager = AdminReportManager(admin_ids=[1322401802, 7176469093])

        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        # self.application.add_handler(CommandHandler("p", self.price_command))
        # self.application.add_handler(CommandHandler("r", self.price_command))
        self.application.add_handler(CommandHandler("c", self.chart_command))
        self.application.add_handler(CommandHandler("fearindex", self.fear_index_command))
        self.application.add_handler(CommandHandler("status", self.status_command))

        # PNL Handlers (pastikan fungsi-fungsi ini diimpor)
        self.application.add_handler(CommandHandler("scan", scan_command))
        self.application.add_handler(CommandHandler("pnl", pnl_command))
        self.application.add_handler(CommandHandler("scans", list_scans_command))

        # Admin Report Handlers (gunakan self. karena merupakan metode kelas)
        self.application.add_handler(CommandHandler("addreport", self.admin_report_manager.add_report))
        self.application.add_handler(CommandHandler("resetreports", self.admin_report_manager.reset_reports))
        self.application.add_handler(CommandHandler("showreports", self.admin_report_manager.show_reports))
        self.application.add_handler(CommandHandler("toggle", self.admin_report_manager.toggle_reports))
        self.application.add_handler(CommandHandler("promo", self.promo_command))

        # Leaderboard Handlers
        self.application.add_handler(CommandHandler("lb", leaderboard_command))
        self.application.add_handler(CallbackQueryHandler(leaderboard_command, pattern='^leaderboard_'))

        # Generic Handlers
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.application.add_handler(MessageHandler(
            (filters.PHOTO | filters.ANIMATION | filters.Document.ALL),
            self.handle_media_with_caption
        ))

    async def promo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})
        link_emoji = CE.get("link", {}).get("char", "🔗")
        await update.message.reply_text(
            f"{link_emoji} **Promo Info:** Contact [@CharlieFourtis](https://t.me/CharlieFourtis).",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )

    def get_animated_emoji(self, regular_emoji: str, animated_emoji_key: str) -> str:
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})
        return CE.get(animated_emoji_key, {}).get("char", regular_emoji)

    async def handle_media_with_caption(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Abaikan media, tapi kalau ada caption → treat as text query (lempar ke handle_text).
        """
        if not update.message or not update.message.caption:
            return

        caption = update.message.caption.strip()
        if not caption:
            return

        # Lempar ke handle_text dengan caption sebagai query_text
        await self.handle_text(update, context, query_text=caption)

    async def leaderboard_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Displays the leaderboard with interactive buttons."""
        try:
            await leaderboard_command(update, context, period='1D')
        except telegram.error.BadRequest as e:
            error_msg = f"A formatting error occurred: {e}\n\nPlease try again later. If the issue persists, contact the administrator."
            # Send a sanitized error message to prevent a crash
            await update.effective_chat.send_message(
                text=escape_all_markdown_v2(error_msg),
                parse_mode='MarkdownV2'
            )
        except Exception as e:
            error_msg = f"An unexpected error occurred: {e}"
            await update.effective_chat.send_message(
                text=escape_all_markdown_v2(error_msg),
                parse_mode='MarkdownV2'
            )

    async def leaderboard_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles callbacks from the leaderboard buttons."""
        query = update.callback_query
        await query.answer()

        try:
            await leaderboard_command(update, context)
        except telegram.error.BadRequest as e:
            error_msg = f"A formatting error occurred: {e}\n\nPlease try again later. If the issue persists, contact the administrator."
            # Send a sanitized error message to prevent a crash
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=escape_all_markdown_v2(error_msg),
                parse_mode='MarkdownV2'
            )
        except Exception as e:
            error_msg = f"An unexpected error occurred: {e}"
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=escape_all_markdown_v2(error_msg),
                parse_mode='MarkdownV2'
            )
        # ================= broadcast_stats_job =================

    async def broadcast_stats_job(self, context):
        """
        Kirim status terbaru ke user tertentu (5231963014)
        """
        from stats_manager import get_status_message, load_stats

        # pastikan stats ter-load
        load_stats()

        # hanya kirim ke user tertentu
        AUTHORIZED_USER = 5231963014
        message = get_status_message()

        try:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"✅ Status message sent to {AUTHORIZED_USER}")
        except Exception as e:
            logger.error(f"❌ Failed to send status message to {AUTHORIZED_USER}: {e}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # === tracking stats ===
        track_chat(update.effective_chat)

        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        diamond2 = CE.get('diamond2', {}).get('char', '💎')
        rocket = CE.get('rocket', {}).get('char', '🚀')
        neutral_face = CE.get('neutral_face', {}).get('char', '😱')
        memo = CE.get('memo', {}).get('char', '❓')

        start_message = (
            f"{diamond2} **Hey there, Crypto Explorer!** {rocket}\n\n"
            "💎 Welcome to FourtisScanBot! **Crypto Price & Scanner Bot!**\n\n"
            "⚡ **What I can do for you:**\n"
            "• 🚀 Track token prices in real-time across 5 major blockchains\n"
            "• 🔍 Scan any contract address like a pro detective\n"
            "• 📈 Keep an eye on the BTC Fear & Greed Index\n\n"
            "📲 **Quick Commands to get started:**\n"
            "• <token> - Detailed price info & stats\n"
            "• /fearindex - What's the BTC Fear & Greed mood?\n"
            "• /scans - Check your scanned token stats\n"
            "• /lb - See the scan leaderboard.\n"
            "• /pnl - View the P&L (Profit & Loss) performance of your tracked tokens.\n"
            "• /showreports - Display active promotions. (Admin only)\n"
            "• /addreport - Add a new promotion. (Admin only)\n"
            "• /resetreports - Delete all promos (Admin only)\n\n"
            "🔥 **Supported Chains:**\n"
            "🔷 Ethereum • 🟡 BSC • 🟣 Solana • 🔵 Base • 🔴 Tron\n\n"
            "💡 Type /help anytime to unlock the full power of your crypto sidekick!"
        )

        start_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{neutral_face} Fear Index", callback_data="fearindex"),
                InlineKeyboardButton(f"{rocket} Website", url="https://fourtis.io/")
            ],
            [
                InlineKeyboardButton(f"{memo} Help", callback_data="help")
            ]
        ])

        if update.message:
            await update.message.reply_text(start_message, parse_mode=ParseMode.MARKDOWN, reply_markup=start_keyboard)
        elif update.callback_query:
            await update.callback_query.message.reply_text(
                start_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=start_keyboard
            )

    async def status_command(self, update: 'Update', context: ContextTypes.DEFAULT_TYPE):
        """Contoh handler status: simpan chat lalu balas status (pakai HTML)"""
        track_chat(update.effective_chat)  # pastikan track_chat berasal dari stats_manager
        status_text = get_status_message()
        await update.message.reply_text(status_text, parse_mode="HTML")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # === tracking stats ===
        track_chat(update.effective_chat)

        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        # Safe emoji helper
        def emoji(name, default='💠'):
            return CE.get(name, {}).get('char', default)

        help_message = f"""
    {emoji('books', '📚')} **Crypto Command Reference**

    ⚡ **Price & Charts:**  
    • `<$name/address>` - Get detailed token analysis & stats  

    📊 **Market Data:**  
    • `{emoji('neutral_face', '😱')} /fearindex` - BTC Fear & Greed Index  

    💡 **Quick Usage Examples:**  
    • `$symbol ` - Detailed token info  
    • `0x...` - Paste any contract address for DEX token analysis  

    💎 **Other Commands:**
    • `/scans` - Check your scanned token stats
    • `/pnl` - View the P&L (Profit & Loss) performance of your tracked tokens.
    • `/lb` - See the scan leaderboard.

    👑 **Admin-Only Commands:**  
    • `/showreports` - View current promos  
    • `/addreport` - Add a new promo  
    • `/resetreports` - Delete all promos  

    🔗 **Supported Chains:**  
    {emoji('eth', '🔷')} Ethereum • {emoji('bsc', '🟡')} BSC • {emoji('sol', '🟣')} Solana • {emoji('base', '🔵')} Base • {emoji('tron', '🔴')} Tron  

    💡 Tip: Just type a token name or paste a contract address to start exploring!
    """

        help_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{emoji('neutral_face', '😱')} Fear Index", callback_data="fearindex"),
                InlineKeyboardButton(f"{emoji('rocket', '🚀')} Website", url="https://fourtis.io/")
            ],
            [
                InlineKeyboardButton("🏠 Main Menu", callback_data="start")
            ]
        ])

        await update.message.reply_text(help_message, parse_mode=ParseMode.MARKDOWN, reply_markup=help_keyboard)

    # Di dalam telegram_bot.py, di dalam class CryptoBot
    async def price_command(self, update: Update, context):
        """
        Handle /p and /r commands using custom emojis
        """

        # === Tracking stats ===
        track_chat(update.effective_chat)
        track_scan()

        # === Config emojis ===
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})
        idea = CE.get("idea", {}).get("char", "💡")
        magnifier = CE.get("magnifier", {}).get("char", "🔍")
        repeat = CE.get("repeat", {}).get("char", "🔄")
        chart = CE.get("chart", {}).get("char", "📊")
        alarm = CE.get("alarm", {}).get("char", "⏰")
        bank = CE.get("bank", {}).get("char", "🏦")
        cross = CE.get("cross", {}).get("char", "❌")

        # === Check if user provided a query ===
        if not context.args:
            await update.message.reply_text(
                f"{idea} **Usage:** ` <$token name or contract address>`\n\n"
                "**Examples:**\n"
                f"• ` $bitcoin`\n"
                f"• ` $ethereum`\n"
                f"• ` 0x...` (contract address)",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        query = " ".join(context.args).strip()

        # === Send analyzing/loading message ===
        loading_emoji = f"{magnifier}{repeat}"
        await update.message.reply_text(
            f"{loading_emoji} **Analyzing:** `{escape_markdown(query)}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            # ✅ PERBAIKAN KRITIS: Menguraikan tuple yang dikembalikan
            report, final_query, detected_chain = await handle_price_command(query)

            # === Auto-save scan in background (non-blocking) ===
            try:
                async def _auto_save_price_scan():
                    try:
                        from pnl_manager import save_scan_row
                        uid = update.effective_user.id
                        uname = (
                                update.effective_user.username
                                or update.effective_user.first_name
                                or str(uid)
                        )
                        chat_id = update.effective_chat.id

                        # ✅ Mengekstrak market cap dari string report
                        mcap_match = re.search(r'MC:\s+\$([\d.]+[KM]?)', report)
                        if mcap_match:
                            mcap_str = mcap_match.group(1)
                            # Mengubah K, M, B ke format float yang benar
                            mcap = float(mcap_str.replace('K', 'e3').replace('M', 'e6').replace('B', 'e9'))
                        else:
                            mcap = None  # Menangani kasus di mana MC tidak ditemukan

                        # ✅ Meneruskan nilai yang benar ke save_scan_row
                        if mcap:
                            save_scan_row(
                                uid,
                                uname,
                                final_query,
                                final_query,
                                detected_chain or "unknown",
                                mcap,
                                chat_id,
                            )
                    except Exception as e:
                        logger.error(f"❌ Error in auto-save scan: {e}", exc_info=True)

                asyncio.create_task(_auto_save_price_scan())
            except Exception:
                pass

            # === Check if token is major coin ===
            from main import CryptoPriceScannerBot
            bot = CryptoPriceScannerBot()
            # ✅ Menggunakan final_query yang telah diuraikan
            is_major = bot.is_major_coin(final_query)

            # === Inline keyboard ===
            keyboard = []
            row1 = []
            if not is_major:
                # ✅ Menggunakan final_query untuk callback data
                row1.append(InlineKeyboardButton(f"{chart} Chart", callback_data=f"chart_{final_query}"))
                row1.append(InlineKeyboardButton(f"{repeat} Refresh", callback_data=f"price_{final_query}"))
                keyboard.append(row1)

            keyboard.append(
                [
                    InlineKeyboardButton(f"{alarm} Fear Index", callback_data="fearindex"),
                    InlineKeyboardButton(f"{bank} Menu", callback_data="start"),
                ]
            )
            reply_markup = InlineKeyboardMarkup(keyboard)

            # === Send report ===
            if len(report) > 4000:
                head = report[:3900] + "\n\n(continued...)"
                tail = report[3900:]
                await update.message.reply_text(
                    head, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
                )
                await update.message.reply_text(tail, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(
                    report, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
                )

        except Exception as e:
            logger.error(f"{cross} Price command error: {e}", exc_info=True)
            await update.message.reply_text(
                f"{cross} **Error fetching price data:** `{str(e)}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    async def chart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /c command with chart generation (image + details + inline keyboard)."""
        track_chat(update.effective_chat)
        track_scan()

        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        def get_emoji(key: str, fallback: str) -> str:
            return CE.get(key, {}).get("char", fallback)

        idea = get_emoji("idea", "💡")
        chart_emoji = get_emoji("chart", "📊")
        magnifier = get_emoji("magnifier", "🔍")
        stopwatch = get_emoji("stopwatch", "⏱️")
        repeat = get_emoji("repeat", "🔄")
        money = get_emoji("money", "💰")
        bank = get_emoji("bank", "🏦")
        cross = get_emoji("cross", "❌")

        # Check arguments
        if not context.args:
            await update.message.reply_text(
                f"{idea} **Chart Command Usage:**\n\n"
                f"{chart_emoji} `/c <token> [timeframe]`\n\n"
                "**Examples:**\n"
                f"• `/c bitcoin` (default 1h)\n"
                f"• `/c ethereum 4h`\n"
                f"• `/c BTC 1d`\n"
                f"• `/c 0x...` (contract address)\n\n"
                "**Available timeframes:**\n"
                "`1m` `5m` `15m` `30m` `1h` `4h` `1d` `1w`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        query = context.args[0]
        timeframe = context.args[1] if len(context.args) > 1 else "1h"

        # Loading message
        loading_msg = await update.message.reply_text(
            f"{chart_emoji} **Generating Chart**\n"
            f"{magnifier} **Token:** `{query}`\n"
            f"{stopwatch} **Timeframe:** `{timeframe}`\n"
            f"{repeat} **Processing...**",
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            # Get chart from bot core
            caption, chart_type, chart_path = await handle_chart_command(query, timeframe)

            # Inline keyboard
            keyboard = [
                [
                    InlineKeyboardButton(f"{chart_emoji} 1h", callback_data=f"chart_{query}_1h"),
                    InlineKeyboardButton(f"{chart_emoji} 4h", callback_data=f"chart_{query}_4h"),
                    InlineKeyboardButton(f"{chart_emoji} 1d", callback_data=f"chart_{query}_1d"),
                ],
                [
                    # InlineKeyboardButton(f"{money} Price Info", callback_data=f"price_{query}"),
                    InlineKeyboardButton(f"{bank} Main Menu", callback_data="start"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if chart_type in ["MAJOR_COIN_CHART", "NO_DATA", "ERROR"]:
                # Just text, no image
                await loading_msg.edit_text(
                    caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                    disable_web_page_preview=False,
                )


            elif chart_type == "DEX_CHART" and chart_path:

                # Compress dulu sebelum kirim

                from chart_renderer import compress_image

                compressed_path = compress_image(chart_path)

                await loading_msg.delete()

                with open(compressed_path, "rb") as photo_file:

                    await update.message.reply_photo(

                        photo=photo_file,

                        caption=caption,

                        parse_mode=ParseMode.MARKDOWN,

                        reply_markup=reply_markup,

                    )
            else:
                # Fallback if something unexpected
                await loading_msg.edit_text(
                    f"{cross} **No Chart Data Available**\n\n"
                    f"**Could not generate chart for:** `{query}`\n\n"
                    f"{idea} **Try:**\n"
                    f"• Check token name/symbol\n"
                    f"• Use contract address\n"
                    f"• Try a different token",
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception as e:
            logger.error(f"{cross} Chart command error: {e}", exc_info=True)
            error_msg = (
                f"{cross} **Chart Generation Error**\n\n"
                f"**Failed to create chart for:** `{query}`\n"
                f"**Please try again.**"
            )
            try:
                await loading_msg.edit_text(error_msg, parse_mode=ParseMode.MARKDOWN)
            except:
                await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)

    async def timeframe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle commands like /1h, /4h with safe Markdown and chart generation."""
        track_chat(update.effective_chat)
        track_scan()

        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        def emoji(key: str, fallback: str = '💠') -> str:
            return CE.get(key, {}).get('char', fallback)

        # Extract timeframe from command
        command = update.message.text.lstrip('/').split()[0]

        if not context.args:
            await update.message.reply_text(
                f"{emoji('idea')} **Usage:** `/{command} <token name>`\n\n"
                f"**Example:** `/{command} bitcoin`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        query = " ".join(context.args)
        await self.chart_command_with_timeframe(update, context, query, command)

    async def chart_command_with_timeframe(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, timeframe: str
    ):
        """Generate chart for a specific timeframe with safe Markdown and emojis."""
        track_chat(update.effective_chat)
        track_scan()

        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        def emoji(name: str, default: str = '💠') -> str:
            return CE.get(name, {}).get('char', default)

        try:
            loading_msg = await update.message.reply_text(
                f"{emoji('chart')} **Generating {escape_md(timeframe.upper())} chart for:** `{escape_md(query)}`\n"
                f"{emoji('repeat')} **Processing...**",
                parse_mode=ParseMode.MARKDOWN
            )

            # Generate chart
            caption, chart_type, chart_path = await handle_chart_command(query, timeframe)

            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"{emoji('chart')} 1h", callback_data=f"chart_{query}_1h"),
                    InlineKeyboardButton(f"{emoji('chart')} 4h", callback_data=f"chart_{query}_4h"),
                    InlineKeyboardButton(f"{emoji('chart')} 1d", callback_data=f"chart_{query}_1d"),
                ],
                [
                    # InlineKeyboardButton(f"{emoji('money')} Price Info", callback_data=f"price_{query}"),
                    InlineKeyboardButton(f"{emoji('bank')} Main Menu", callback_data="start"),
                ]
            ])

            chart_message = f"""
    {emoji('chart')} **{escape_md(query.upper())} Chart - {escape_md(timeframe.upper())}**

    {escape_md(caption) if caption else ""}
    """

            if chart_path:
                from chart_renderer import compress_image
                compressed_path = compress_image(chart_path)

                await loading_msg.delete()
                await update.message.reply_photo(
                    photo=open(compressed_path, "rb"),
                    caption=chart_message,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )

            else:
                # Otherwise just edit text
                try:
                    await loading_msg.edit_text(chart_message, parse_mode=ParseMode.MARKDOWN,
                                                reply_markup=reply_markup)
                except:
                    await update.message.reply_text(chart_message, parse_mode=ParseMode.MARKDOWN,
                                                    reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"{emoji('cross')} Chart generation error: {e}")
            error_msg = f"{emoji('cross')} **Error generating chart for:** `{escape_md(query)}`"
            try:
                await loading_msg.edit_text(error_msg, parse_mode=ParseMode.MARKDOWN)
            except:
                await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str = None):
        """
        Handle text messages or caption from media,
        detect addresses or links, and process them.
        """
        if not update.message:
            return

        # 🔹 kalau ada query_text (misalnya dari caption), pakai itu
        query = query_text.strip() if query_text else (update.message.text.strip() if update.message.text else None)

        if not query or query.startswith("/"):
            return

        # ✅ Regex tetap sama
        pattern = (
            r'(https?://dexscreener\.com/\w+/(?:0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44}|T[a-zA-Z0-9]{33}))'  # link dexscreener
            r'|(0x[a-fA-F0-9]{40})'  # evm contract
            r'|(\b[1-9A-HJ-NP-Za-km-z]{32,44}\b)'  # pair id
            r'|(T[a-zA-Z0-9]{33})'  # tron
            r'|(\$[A-Z][A-Z0-9]{1,9})'  # symbol (harus diawali huruf)
        )

        match = re.search(pattern, query, re.IGNORECASE)
        if not match:
            return

        # Ambil sesuai prioritas
        link, evm_contract, pairid, tron_addr, symbol = match.groups()

        if link:
            extracted_query = link
        elif evm_contract:
            extracted_query = evm_contract
        elif pairid:
            extracted_query = pairid
        elif tron_addr:
            extracted_query = tron_addr
        elif symbol:
            extracted_query = symbol
        else:
            return

        # Handle $SYMBOL → buang prefix $
        if extracted_query.startswith('$'):
            extracted_query = extracted_query.lstrip('$')

        try:
            search_emoji = self.get_animated_emoji(emoji('magnifier'), emoji('diamond'))
            await update.message.reply_text(
                f"{search_emoji} **Analyzing contract/address:** `{extracted_query}`",
                parse_mode=ParseMode.MARKDOWN
            )

            report, final_query, detected_chain = await handle_price_command(extracted_query)

            await update.message.reply_text(
                report,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(f"{emoji('chart')} Chart", callback_data=f"chart_{final_query}"),
                        InlineKeyboardButton(f"{emoji('repeat')} Refresh", callback_data=f"price_{final_query}")
                    ],
                    [
                        InlineKeyboardButton(f"{emoji('fear')} Fear Index", callback_data="fearindex"),
                        InlineKeyboardButton(f"{emoji('bank')} Menu", callback_data="start")
                    ]
                ])
            )

            # Simpan hasil scan ke stats_manager
            asyncio.create_task(process_and_save_scan(update, context, final_query))

        except BadRequest as e:
            await update.message.reply_text(
                f"{emoji('cross')} **Error: The bot failed to send the report.**\n\nIssue: `{str(e)}`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await update.message.reply_text(
                f"{emoji('cross')} **Error fetching data:** `{str(e)}`",
                parse_mode=ParseMode.MARKDOWN
            )

        # If input is not a supported blockchain address, do nothing

    async def fear_index_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        track_chat(update.effective_chat)
        track_scan()
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})
        chart_emoji = CE.get('chart', {}).get('char', '📊')
        repeat = CE.get('repeat', {}).get('char', '🔄')
        bank = CE.get('bank', {}).get('char', '🏦')
        rocket = CE.get('rocket', {}).get('char', '🚀')
        cross = CE.get('cross', {}).get('char', '❌')

        loading_msg = await update.message.reply_text(f"{chart_emoji} **Fetching Fear & Greed Index...**",
                                                      parse_mode=ParseMode.MARKDOWN)
        try:
            report = await handle_fear_index_command()
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(f"{repeat} Refresh", callback_data="fearindex"),
                    InlineKeyboardButton(f"{rocket} Website", url="https://fourtis.io/")
                ],
                [
                    InlineKeyboardButton(f"{bank} Menu", callback_data="start")
                ]
            ])
            await loading_msg.edit_text(
                report,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"{cross} Fear index command error: {e}")
            await loading_msg.edit_text(
                f"{cross} **Error fetching Fear & Greed Index:** `{str(e)}`",
                parse_mode=ParseMode.MARKDOWN
            )

    # async def fed_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # """Handle /fed command"""
    # loading_msg = await update.message.reply_text(
    #   "🏛️ **Fetching Fed Watch data...**",
    #  parse_mode=ParseMode.MARKDOWN
    # )

    # try:
    #   report = await handle_fed_command()
    #
    #  keyboard = [
    #               [
    #                  InlineKeyboardButton("🔄 Refresh", callback_data="fed"),
    #                 InlineKeyboardButton("😱 Fear Index", callback_data="fearindex")
    #            ],
    #           [
    #              InlineKeyboardButton("🔥 Trending", callback_data="trending"),
    #             InlineKeyboardButton("🏠 Menu", callback_data="start")
    #        ]
    #   ]
    #  reply_markup = InlineKeyboardMarkup(keyboard)
    #
    #           await loading_msg.edit_text(
    #              report,
    #             parse_mode=ParseMode.MARKDOWN,
    ##       )
    #  except Exception as e:
    #     logger.error(f"Fed command error: {e}")
    ##       f"❌ **Error fetching Fed Watch data:** `{str(e)}`",
    #      parse_mode=ParseMode.MARKDOWN
    # )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks with charts, price info, fear index, etc."""
        track_chat(update.effective_chat)
        track_scan()

        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        def emoji(name: str, default: str = '💠') -> str:
            return CE.get(name, {}).get('char', default)

        query = update.callback_query
        await query.answer()
        data = query.data

        async def safe_edit_or_send(msg_obj, text, reply_markup=None, disable_preview=True):
            try:
                await msg_obj.edit_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_preview
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_preview
                )

        try:
            # === Start Menu ===
            if data == "start":
                await safe_edit_or_send(query.message, self._get_start_message(), self._get_start_keyboard())

            # === Help ===
            elif data == "help":
                await safe_edit_or_send(query.message, self._get_help_message(), self._get_help_keyboard())

            # === Chart Buttons ===
            elif data.startswith("chart_"):
                parts = data.replace("chart_", "").split("_")
                token = parts[0]
                timeframe = parts[1] if len(parts) > 1 else "1h"
                await handle_chart_button(token, timeframe, query, context)

            # === Price Buttons ===
            # di bagian price_ callback
            elif data.startswith("price_"):
                token = data.replace("price_", "")

                loading_msg = await query.message.reply_text(
                    f"{emoji('magnifier')} **Fetching price for:** `{escape_md(token)}`",
                    parse_mode=ParseMode.MARKDOWN
                )

                try:
                    from main import CryptoPriceScannerBot, handle_price_command

                    # inisialisasi bot helper untuk cek major coin
                    scanner_bot = CryptoPriceScannerBot()

                    report = await handle_price_command(token)

                    # Build keyboard
                    keyboard = []

                    # Bar pertama: Chart button hanya jika bukan major coin
                    first_row = []
                    if not scanner_bot.is_major_coin(token):
                        first_row.append(
                            InlineKeyboardButton(f"{emoji('chart')} Chart", callback_data=f"chart_{token}")
                        )
                    first_row.append(
                        InlineKeyboardButton(f"{emoji('repeat')} Refresh", callback_data=f"price_{token}")
                    )

                    keyboard.append(first_row)

                    # Bar kedua: selalu ada Menu
                    keyboard.append([InlineKeyboardButton(f"{emoji('bank')} Menu", callback_data="start")])

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    # Kirim / edit message
                    try:
                        await safe_edit_or_send(loading_msg, report, reply_markup)
                    except Exception:
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=report,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=reply_markup
                        )

                except Exception as e:
                    logger.error(f"Price callback error: {e}")
                    await safe_edit_or_send(
                        loading_msg,
                        f"{emoji('cross')} **Error fetching price:** `{escape_md(str(e))}`"
                    )


            # === Fear & Greed Index ===
            elif data == "fearindex":
                loading_msg = await query.message.reply_text(
                    f"{emoji('chart')} **Fetching Fear & Greed Index...**",
                    parse_mode=ParseMode.MARKDOWN
                )

                try:
                    report = await handle_fear_index_command()
                    keyboard = [
                        [
                            InlineKeyboardButton(f"{emoji('repeat')} Refresh", callback_data="fearindex"),
                            InlineKeyboardButton(f"{emoji('rocket')} Website", url="https://fourtis.io/")
                        ],
                        [
                            InlineKeyboardButton(f"{emoji('bank')} Menu", callback_data="start")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await safe_edit_or_send(loading_msg, report, reply_markup)

                except Exception as e:
                    logger.error(f"Fear index callback error: {e}")
                    await safe_edit_or_send(
                        loading_msg,
                        f"{emoji('cross')} **Error fetching Fear & Greed Index:** `{escape_md(str(e))}`"
                    )

        except Exception as e:
            logger.error(f"Button callback error: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{emoji('cross')} **Error Processing Request**\n\nPlease try again or use text commands.",
                parse_mode=ParseMode.MARKDOWN
            )

    def _get_start_message(self) -> str:
        """Get start message using custom emoji IDs for all users"""
        CE = self.config.CUSTOM_EMOJI_IDS  # Shortcut

        # Safe emoji helper
        def emoji(name, default='💠'):
            return CE.get(name, {'char': default})['char']

        return f"""
    {emoji('crown')} **Hey there, Crypto Explorer! Welcome aboard!** {emoji('rocket')}

    💎 **Your Ultimate Crypto Sidekick:**  
    • 🚀 Real-time token price tracking across 5 major blockchains  
    • 🔍 Contract address scanning like a crypto detective  
    • 📈 Monitoring BTC Fear & Greed Index  

    📲 **Quick Commands to Get Started:**  
    • `<$symbol/Contractaddress>` - Detailed price info & stats  
    • `/fearindex` - Check BTC Fear & Greed mood  
    • `/help` - See other commands
    • `/showreports` - View current promos (Admin only)  
    • `/addreport` - Create a new promo (Admin only)  
    • `/resetreports` - Delete all promos (Admin only)  

    🔥 **Supported Chains:**  
    {emoji('eth', '🔷')} Ethereum • {emoji('bsc', '🟡')} BSC • {emoji('sol', '🟣')} Solana • {emoji('base', '🔵')} Base • {emoji('tron', '🔴')} Tron  

    💡 Tip: paste a contract address to dive in instantly!
    """

    def _get_start_keyboard(self) -> InlineKeyboardMarkup:
        """Return start keyboard using custom emoji IDs safely"""
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        # Safe emoji helper
        def emoji(name: str, default: str = '💠') -> str:
            return CE.get(name, {}).get('char', default)

        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{emoji('alarm', '⏰')} Fear Index", callback_data="fearindex"),
                InlineKeyboardButton(f"{emoji('rocket', '🚀')} Website", url="https://fourtis.io/")
            ],
            [
                InlineKeyboardButton(f"{emoji('memo', '📝')} Help", callback_data="help")
            ]
        ])

    def _get_help_message(self):
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        def emoji(name, default='💠'):
            return CE.get(name, {'char': default})['char']

        return f"""
    {emoji('books')} **Hey Crypto Explorer! Here's what I can do for you:**  

    ⚡ **Price & Token Analysis:**
    • `<token>` - Get detailed price info, stats & charts


    📊 **Market Insights:**
    • `/fearindex` - See BTC Fear & Greed Index

    💎 **Other Commands:**
    • `/scans` - Check your scanned token stats
    • `/pnl` - View the P&L (Profit & Loss) performance of your tracked tokens.
    • `/lb` - See the scan leaderboard.
    • `/showreports` - Display active promotions. (Admin only)
    • `/addreport` - Add a new promotion. (Admin only)
    • `/resetreports` - Delete all existing promotions. (Admin only)

    🌐 **Supported Chains:**
    {emoji('eth', '🔷')} Ethereum • {emoji('bsc', '🟡')} BSC • {emoji('sol', '🟣')} Solana • {emoji('base', '🔵')} Base • {emoji('tron', '🔴')} Tron

    💡 Tip: Paste contract address to get started instantly!
    """

    def _get_help_keyboard(self):
        """Get help keyboard using custom emoji IDs safely"""
        CE = getattr(self.config, "CUSTOM_EMOJI_IDS", {})

        # Safe emoji helper
        def emoji(name: str, default: str = '💠') -> str:
            return CE.get(name, {}).get('char', default)

        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{emoji('alarm', '⏰')} Fear Index", callback_data="fearindex"),
                InlineKeyboardButton(f"{emoji('rocket', '🔥')} Website", url="https://fourtis.io/")
            ],
            [
                InlineKeyboardButton(f"{emoji('house', '🏠')} Main Menu", callback_data="start")
            ]
        ])

    def run(self):
        """Start the bot"""
        print("🤖 Starting Telegram Crypto Bot...")
        print("📊 Features: Price tracking, Charts, Contract scanning")
        print("🔗 Supported: ETH, BSC, SOL, BASE, TRX")
        print("💎 Animated emojis for all users!")
        self.application.run_polling()


# Example usage
if __name__ == "__main__":
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN_HERE')
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE" or not BOT_TOKEN:
        print("❌ Please set your Telegram bot token in the .env file")
        print("📱 Get your token from @BotFather on Telegram")
        print("💡 Add TELEGRAM_BOT_TOKEN=your_token_here to your .env file")
    else:
        bot = TelegramCryptoBot(BOT_TOKEN)
        bot.run()
