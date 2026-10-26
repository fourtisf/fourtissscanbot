#!/usr/bin/env bash
# botctl.sh — satu perintah untuk mengurus bot di server (via PM2).
#
# Pasang sekali (di folder bot):   bash botctl.sh install
# Setelah itu cukup ketik:
#   bot deploy     ambil kode terbaru branch main, tes, restart (rollback otomatis kalau gagal)
#   bot logs       lihat log live (Ctrl+C untuk keluar)
#   bot status     status bot
#   bot restart    restart bot
#   bot stop       matikan bot
#   bot rollback   kembali ke versi sebelum deploy terakhir
#
# Semua perintah memakai PM2 (app "botscan"). JANGAN jalankan bot lewat systemd
# juga — dua instance = 409 Conflict dari Telegram = bot diam. deploy.sh
# otomatis mematikan unit systemd lama (fourtisbot.service) saat pindah ke PM2.
set -euo pipefail

APP_NAME=botscan
BOT_DIR="${BOT_DIR:-$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)}"

cd "$BOT_DIR"

log()  { echo -e "\033[1;36m==>\033[0m $*"; }
ok()   { echo -e "\033[1;32m✔\033[0m $*"; }
fail() { echo -e "\033[1;31m✘ $*\033[0m" >&2; }

cmd_install() {
    log "Menyiapkan virtualenv & dependency"
    [ -d venv ] || python3 -m venv venv
    venv/bin/pip install -q --upgrade pip
    venv/bin/pip install -q -r requirements.txt
    venv/bin/python -m playwright install --with-deps chromium >/dev/null 2>&1 \
        || echo "   (lewati install Chromium; fitur chart mungkin tidak jalan)"

    command -v pm2 >/dev/null || { fail "pm2 belum terinstall: npm install -g pm2"; exit 1; }

    ln -sf "$BOT_DIR/botctl.sh" /usr/local/bin/bot
    chmod +x "$BOT_DIR/botctl.sh" "$BOT_DIR/deploy.sh"
    ok "Perintah 'bot' terpasang. Coba: bot status"

    bash "$BOT_DIR/deploy.sh" --force "$BOT_DIR"
}

require_pm2_app() {
    pm2 describe "$APP_NAME" >/dev/null 2>&1 \
        || { fail "Bot belum jalan di PM2. Jalankan dulu: bot deploy"; exit 1; }
}

case "${1:-}" in
    install)  cmd_install ;;
    deploy)   bash "$BOT_DIR/deploy.sh" "$BOT_DIR" ;;
    rollback) bash "$BOT_DIR/deploy.sh" --rollback "$BOT_DIR" ;;
    logs)     require_pm2_app; pm2 logs "$APP_NAME" --lines 50 ;;
    status)   pm2 list ;;
    restart)  require_pm2_app; pm2 restart "$APP_NAME" --update-env && ok "Bot di-restart. Cek: bot logs" ;;
    stop)     require_pm2_app; pm2 stop "$APP_NAME" && ok "Bot dimatikan. Nyalakan lagi: bot restart" ;;
    *)        sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
