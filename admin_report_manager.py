from telegram import Update
from telegram.ext import ContextTypes
from promo_manager import add_report as add_promo, reset_reports as reset_promo, get_custom_report
from datetime import datetime, timedelta

class AdminReportManager:
    def __init__(self, admin_ids=None):
        self.admin_ids = set(admin_ids or [])
        self.enabled = True

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    # ----------------------------
    # Add a global promo (text | link | days)
    # ----------------------------
    async def add_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ You are not authorized.")
            return

        if not context.args:
            await update.message.reply_text(
                '❌ Usage: /addreport text | link | days (link optional, days required)'
            )
            return

        # gabungkan args
        full_text = " ".join(context.args)
        parts = full_text.split("|", maxsplit=2)

        if len(parts) < 3:
            await update.message.reply_text("❌ wrong format. usage: text | link | days")
            return

        text = parts[0].strip()
        link = parts[1].strip() or None  # jika kosong, jadi None
        days_str = parts[2].strip()

        # konversi days ke expiry datetime
        try:
            days = int(days_str)
            expiry = datetime.utcnow() + timedelta(days=days)
        except ValueError:
            await update.message.reply_text("❌ Days must be a number, misal 1,3,7,15,30")
            return

        # gabungkan jadi Markdown jika ada link
        promo_text = f"[{text}]({link})" if link else text

        result = await add_promo(promo_text, expiry)
        await update.message.reply_text(f"✅ Promo added, expires in {days} day(s).\n{result}")

    # ----------------------------
    # Reset all promos
    # ----------------------------
    async def reset_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ You are not authorized.")
            return
        result = await reset_promo()
        await update.message.reply_text(result)

    # ----------------------------
    # Toggle promo display
    # ----------------------------
    async def toggle_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ You are not authorized.")
            return
        self.enabled = not self.enabled
        status = "enabled" if self.enabled else "disabled"
        await update.message.reply_text(f"✅ Promo feature is now: {status}")

    # ----------------------------
    # Show all promos
    # ----------------------------
    async def show_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ You are not authorized.")
            return
        promos = await get_custom_report()
        text = "ℹ️ No promos found." if not promos else "🔔 Current Promos:\n" + promos
        await update.message.reply_text(text, parse_mode="Markdown")
