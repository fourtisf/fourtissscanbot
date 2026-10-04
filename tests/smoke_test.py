"""Smoke test: jalankan bot asli melawan Telegram API palsu (tanpa internet).

Cek: bot bisa start, membalas /start, /help dan contract address, dan memasang menu command.
Dijalankan di folder sementara supaya stats.json / scans.db produksi tidak tersentuh.

    python tests/smoke_test.py      -> exit 0 kalau lolos, 1 kalau gagal
"""
import asyncio
import glob
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT = {"id": 111, "type": "private", "first_name": "T"}
USER = {"id": 111, "is_bot": False, "first_name": "T"}
MESSAGES = ["/start", "/help", "0x6982508145454Ce325dDbE47a25d4ec3d2311933"]


def _update(i, text):
    entities = [{"type": "bot_command", "offset": 0, "length": len(text)}] if text.startswith("/") else []
    return {"update_id": i, "message": {"message_id": i, "date": int(time.time()), "chat": CHAT,
                                       "from": USER, "text": text, "entities": entities}}


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="botsmoke_")
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        shutil.copy(path, workdir)
    for d in ("fonts", "templates", "emojis"):
        if os.path.isdir(os.path.join(ROOT, d)):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(workdir, d))
    os.chdir(workdir)
    sys.path.insert(0, workdir)
    os.environ["TELEGRAM_BOT_TOKEN"] = "123:SMOKE"
    os.environ.pop("HEALTHCHECK_URL", None)

    from telegram.request import HTTPXRequest
    replies, commands, served = [], [], {"done": False}

    async def do_request(self, url, method, request_data=None, read_timeout=None, **kw):
        ep = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        if ep == "getMe":
            r = {"id": 1, "is_bot": True, "first_name": "B", "username": "smokebot"}
        elif ep == "getUpdates":
            if not served["done"]:
                served["done"] = True
                r = [_update(i + 1, t) for i, t in enumerate(MESSAGES)]
            else:
                await asyncio.sleep(0.5)
                r = []
        elif ep == "getWebhookInfo":
            r = {"url": "", "has_custom_certificate": False, "pending_update_count": 0}
        elif ep == "setMyCommands":
            cmds = params.get("commands")
            commands.extend(json.loads(cmds) if isinstance(cmds, str) else cmds or [])
            r = True
        elif ep in ("sendMessage", "sendPhoto", "editMessageText"):
            replies.append(str(params.get("text") or params.get("caption") or ""))
            r = {"message_id": 99, "date": int(time.time()), "chat": CHAT, "text": "x"}
        else:
            r = True
        return 200, json.dumps({"ok": True, "result": r}).encode()

    async def initialize(self):
        pass

    HTTPXRequest.do_request = do_request
    HTTPXRequest.initialize = initialize

    import telegram_bot
    bot = telegram_bot.TelegramCryptoBot("123:SMOKE")
    original_post_init = bot.application.post_init

    async def post_init(app):
        await original_post_init(app)

        async def stop_later():
            await asyncio.sleep(8)
            app.stop_running()
        asyncio.get_running_loop().create_task(stop_later())

    bot.application.post_init = post_init
    bot.application.run_polling()

    checks = {
        "/start dibalas": any("Welcome" in r for r in replies),
        "/help dibalas": any("Command" in r or "what I can do" in r for r in replies),
        "contract address diproses": any("Analyzing" in r for r in replies),
        "menu command dipasang": any(c.get("command") == "start" for c in commands),
    }
    shutil.rmtree(workdir, ignore_errors=True)
    for name, ok in checks.items():
        print(f"{'✅' if ok else '❌'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
