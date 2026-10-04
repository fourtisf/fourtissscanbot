#!/usr/bin/env bash
# botctl.sh — satu perintah untuk mengurus bot di server.
#
# Pasang sekali (di folder bot):   bash botctl.sh install
# Setelah itu cukup ketik:
#   bot deploy     ambil kode terbaru dari GitHub, tes, restart (rollback otomatis kalau gagal)
#   bot logs       lihat log live (Ctrl+C untuk keluar)
#   bot status     status bot
#   bot restart    restart bot
#   bot stop       matikan bot
#   bot rollback   kembali ke versi sebelum deploy terakhir
set -euo pipefail

SERVICE=fourtisbot
BOT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
BACKUP_ROOT="$HOME/bot-backups"
# File data yang TIDAK ada di git dan tidak boleh hilang saat deploy
DATA_FILES=(.env stats.json stats_backup.json scans.db promo.json)

cd "$BOT_DIR"

log()  { echo -e "\033[1;36m==>\033[0m $*"; }
ok()   { echo -e "\033[1;32m✔\033[0m $*"; }
fail() { echo -e "\033[1;31m✘ $*\033[0m" >&2; }

backup_data() {
    local dest="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$dest"
    for f in "${DATA_FILES[@]}"; do
        if [ -e "$f" ]; then cp -p "$f" "$dest/"; fi
    done
    git rev-parse HEAD > "$dest/COMMIT"
    # simpan 15 backup terakhir saja
    ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | tail -n +16 | xargs -r rm -rf
    echo "$dest"
}

restore_data() {
    local src="$1"
    # selalu timpa dari backup: git reset bisa menghapus/menimpa file data
    for f in "${DATA_FILES[@]}"; do
        if [ -e "$src/$f" ]; then cp -p "$src/$f" "$f"; fi
    done
}

wait_healthy() {
    local since="$1"
    for _ in $(seq 1 30); do
        if journalctl -u "$SERVICE" --since "@$since" --no-pager 2>/dev/null | grep -q "Logged in as"; then
            systemctl is-active --quiet "$SERVICE" && return 0
        fi
        sleep 1
    done
    return 1
}

restart_and_check() {
    local since
    since=$(date +%s)
    systemctl restart "$SERVICE"
    wait_healthy "$since"
}

cmd_install() {
    log "Menyiapkan virtualenv & dependency"
    [ -d venv ] || python3 -m venv venv
    venv/bin/pip install -q --upgrade pip
    venv/bin/pip install -q -r requirements.txt
    venv/bin/python -m playwright install --with-deps chromium >/dev/null 2>&1 \
        || echo "   (lewati install Chromium; fitur chart mungkin tidak jalan)"

    log "Memasang service systemd ($SERVICE)"
    cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=Fourtis Scan Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python telegram_bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$SERVICE" >/dev/null

    ln -sf "$BOT_DIR/botctl.sh" /usr/local/bin/bot
    chmod +x "$BOT_DIR/botctl.sh"
    ok "Perintah 'bot' terpasang. Coba: bot status"

    if restart_and_check; then ok "Bot jalan."; else fail "Bot belum sehat, cek: bot logs"; fi
}

cmd_deploy() {
    local branch prev backup
    branch=$(git rev-parse --abbrev-ref HEAD)
    prev=$(git rev-parse HEAD)

    backup=$(backup_data)
    log "Backup data → $backup"

    log "Ambil kode terbaru (branch $branch)"
    git fetch origin "$branch"
    if [ "$(git rev-parse "origin/$branch")" = "$prev" ]; then
        ok "Sudah versi terbaru ($(git log --oneline -1))"
        return 0
    fi
    git reset --hard "origin/$branch"
    restore_data "$backup"
    git log --oneline "$prev..HEAD" | sed 's/^/   + /'

    log "Install dependency"
    venv/bin/pip install -q -r requirements.txt

    log "Smoke test"
    if ! venv/bin/python tests/smoke_test.py; then
        fail "Smoke test gagal — rollback ke $prev"
        git reset --hard "$prev"; restore_data "$backup"
        return 1
    fi

    log "Restart bot"
    if restart_and_check; then
        ok "Deploy sukses: $(git log --oneline -1)"
    else
        fail "Bot tidak sehat setelah restart — rollback ke $prev"
        journalctl -u "$SERVICE" -n 30 --no-pager || true
        git reset --hard "$prev"; restore_data "$backup"
        restart_and_check && ok "Rollback sukses, bot jalan dengan versi lama." || fail "Rollback juga gagal, cek: bot logs"
        return 1
    fi
}

cmd_rollback() {
    local last
    last=$(ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | head -1)
    [ -n "$last" ] && [ -f "$last/COMMIT" ] || { fail "Tidak ada backup."; exit 1; }
    log "Rollback ke $(cat "$last/COMMIT")"
    git reset --hard "$(cat "$last/COMMIT")"
    restore_data "$last"
    restart_and_check && ok "Rollback sukses." || fail "Bot belum sehat, cek: bot logs"
}

case "${1:-}" in
    install)  cmd_install ;;
    deploy)   cmd_deploy ;;
    rollback) cmd_rollback ;;
    logs)     journalctl -u "$SERVICE" -f -n 50 ;;
    status)   systemctl status "$SERVICE" --no-pager -n 15 ;;
    restart)  restart_and_check && ok "Bot jalan." || fail "Bot belum sehat, cek: bot logs" ;;
    stop)     systemctl stop "$SERVICE" && ok "Bot dimatikan." ;;
    *)        sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
