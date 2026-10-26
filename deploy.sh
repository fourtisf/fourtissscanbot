#!/usr/bin/env bash
#
# deploy.sh — update FourtisScanBot ke versi terbaru branch `main` di GitHub,
# lalu jalankan ulang lewat PM2. Satu perintah, aman diulang kapan saja:
#
#   bash /root/botscan/deploy.sh            # deploy versi terbaru
#   bash /root/botscan/deploy.sh --force    # restart walau sudah versi terbaru
#
# Pertama kali (folder bot belum punya deploy.sh):
#   curl -fsSL https://raw.githubusercontent.com/fourtisf/fourtissscanbot/main/deploy.sh -o /tmp/deploy.sh
#   bash /tmp/deploy.sh /root/botscan
#
# Yang dilakukan:
#   1. Backup data runtime (.env, scans.db, stats*.json, promo.json) ke luar repo.
#   2. Ambil kode branch main. Folder yang belum berupa git repo dikonversi
#      sekali (dengan backup penuh .tgz).
#   3. Install requirements kalau berubah, lalu tes kode bisa di-import.
#      Gagal → kode dikembalikan, bot yang sedang jalan TIDAK disentuh.
#   4. Pindahkan bot dari systemd ke PM2 (sekali saja). Dua supervisor = dua
#      instance = 409 Conflict dari Telegram = bot diam.
#   5. Health check. Bot tidak sehat → rollback otomatis ke kondisi sebelum
#      deploy (termasuk kembali ke systemd kalau tadi dipindahkan).
#
set -Eeuo pipefail

APP_NAME="${APP_NAME:-botscan}"
BRANCH="${BRANCH:-main}"
REPO_URL="${REPO_URL:-https://github.com/fourtisf/fourtissscanbot.git}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/botscan-deploy-backups}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"   # detik menunggu bot konfirmasi start
STABLE_SECS="${STABLE_SECS:-10}"         # bot harus tetap online selama ini
KEEP_BACKUPS=10
# File yang ditulis bot saat berjalan — tidak boleh tertimpa/terhapus git.
RUNTIME_FILES=(.env scans.db stats.json stats_backup.json promo.json)

# Semua logika di dalam main(): bash membaca fungsi utuh sebelum dijalankan,
# jadi aman walau deploy.sh sendiri ikut ter-update oleh git di tengah jalan.
main() {
    local force=0 dir_arg=""
    for arg in "$@"; do
        case "$arg" in
            --force) force=1 ;;
            -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 0 ;;
            *) dir_arg="$arg" ;;
        esac
    done

    BOT_DIR="$(cd "${dir_arg:-$(dirname "${BASH_SOURCE[0]}")}" 2>/dev/null && pwd -P)" \
        || die "Folder tidak ditemukan: ${dir_arg}"
    [ -f "$BOT_DIR/telegram_bot.py" ] \
        || die "$BOT_DIR bukan folder bot (telegram_bot.py tidak ada). Contoh: bash $0 /root/botscan"
    command -v git >/dev/null || die "git belum terinstall: apt install -y git"
    command -v pm2 >/dev/null || die "pm2 belum terinstall: npm install -g pm2"
    cd "$BOT_DIR"

    exec 9>"/tmp/${APP_NAME}-deploy.lock"
    flock -n 9 || die "Deploy lain sedang berjalan. Tunggu sampai selesai."

    STAGE=precheck CONVERTED=0 CODE_CHANGED=0 OLD="" NEW="" BACKUP_DIR=""
    ORIG_BRANCH="" ORIG_MAIN="" PM2_TOUCHED=0 KILLED_STRAYS=0
    MIGRATED_UNITS=()
    trap 'fail "perintah gagal di baris $LINENO"' ERR

    PY="$(detect_python)"
    export BOT_PYTHON="$PY"   # dibaca ecosystem.config.js
    log "Folder bot : $BOT_DIR"
    log "Python     : $PY"

    # --- Status kode ---
    local is_repo=0 cur_branch=""
    if [ "$(git rev-parse --show-toplevel 2>/dev/null || true)" = "$BOT_DIR" ]; then
        is_repo=1
        git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REPO_URL"
        log "Ambil kode terbaru branch $BRANCH dari GitHub..."
        git fetch -q origin "$BRANCH" \
            || die "git fetch gagal dari $(git remote get-url origin) (cek koneksi internet server)."
        NEW="$(git rev-parse FETCH_HEAD)"
        OLD="$(git rev-parse -q --verify HEAD || true)"
        cur_branch="$(git symbolic-ref --short -q HEAD || true)"
        ORIG_BRANCH="$cur_branch"
        ORIG_MAIN="$(git rev-parse -q --verify "refs/heads/$BRANCH" || true)"
        if [ "$OLD" != "$NEW" ] || [ "$cur_branch" != "$BRANCH" ]; then
            CODE_CHANGED=1
        fi
    else
        CODE_CHANGED=1
    fi

    # --- Status proses ---
    local units=() u
    while read -r u; do [ -n "$u" ] && units+=("$u"); done < <(legacy_units)
    local pm2_status
    pm2_status="$(pm2_info | cut -f1)"

    if [ "$CODE_CHANGED" = 0 ] && [ ${#units[@]} -eq 0 ] && [ "$pm2_status" = online ] && [ "$force" = 0 ]; then
        log "✅ Sudah versi terbaru ($(git log -1 --format='%h %s')) dan bot online di PM2."
        log "   Pakai --force untuk restart paksa."
        pm2 list
        exit 0
    fi

    BACKUP_DIR="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    backup_runtime

    # --- Update kode ---
    if [ "$is_repo" = 0 ]; then
        convert_to_git
    elif [ "$CODE_CHANGED" = 1 ]; then
        update_git
    fi

    # --- Dependency + tes import (bot lama masih jalan, belum disentuh) ---
    local installed=0
    if [ "$CONVERTED" = 0 ] && [ -n "$OLD" ] && [ "$OLD" != "$NEW" ] \
        && ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then
        pip_install || fail "pip install requirements gagal (pakai venv: python3 -m venv venv)"
        installed=1
    fi
    if ! smoke_test; then
        if [ "$installed" = 0 ]; then
            warn "Tes import gagal — coba install requirements dulu..."
            pip_install || fail "pip install requirements gagal (pakai venv: python3 -m venv venv)"
            smoke_test || fail "kode baru gagal di-import (lihat $BACKUP_DIR/smoke.log)"
        else
            fail "kode baru gagal di-import (lihat $BACKUP_DIR/smoke.log)"
        fi
    fi
    log "Tes import OK."

    # --- Pindah ke PM2 / restart ---
    STAGE=process
    for u in ${units[@]+"${units[@]}"}; do
        import_unit_env "$u"
        log "Matikan systemd $u (bot pindah ke PM2)..."
        systemctl stop "$u"
        systemctl disable --quiet "$u" 2>/dev/null || true
        MIGRATED_UNITS+=("$u")
    done
    stop_stray_bots
    warn_other_bots
    start_pm2

    if ! health_check; then
        fail "bot tidak sehat setelah start: $HEALTH_REASON"
    fi

    # --- Selesai ---
    STAGE=finished
    trap - ERR
    set +e
    pm2 save >/dev/null || warn "pm2 save gagal — jalankan manual: pm2 save"
    ensure_pm2_startup
    prune_backups

    echo
    log "✅ Deploy berhasil."
    if [ -n "$OLD" ] && [ "$OLD" != "$NEW" ]; then
        log "Perubahan yang ter-deploy:"
        git log --oneline "$OLD..$NEW" | head -20 | sed 's/^/     /'
    fi
    log "Versi sekarang: $(git log -1 --format='%h %s')"
    log "Backup data   : $BACKUP_DIR"
    pm2 list
    log "Lihat log: pm2 logs $APP_NAME"
}

# ==========================
# Helper
# ==========================
log()  { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[deploy] ⚠️  %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[deploy] ❌ %s\033[0m\n' "$*" >&2; exit 1; }

detect_python() {
    local p pid
    for p in "$BOT_DIR/venv/bin/python" "$BOT_DIR/.venv/bin/python"; do
        [ -x "$p" ] && { echo "$p"; return; }
    done
    # Interpreter yang dipakai bot yang sedang jalan (mis. dari systemd)
    for pid in $(bot_pids); do
        p="$(ps -o args= -p "$pid" 2>/dev/null | awk '{print $1}' || true)"
        if [[ "$p" == /* && -x "$p" && "$(basename "$p")" == python* ]]; then
            echo "$p"; return
        fi
    done
    command -v python3 || die "python3 tidak ditemukan"
}

# PID proses telegram_bot.py yang berjalan dari folder bot ini
bot_pids() {
    local pid
    for pid in $(pgrep -f 'telegram_bot\.py' || true); do
        [ "$(readlink "/proc/$pid/cwd" 2>/dev/null || true)" = "$BOT_DIR" ] && echo "$pid"
    done
    return 0
}

# Unit systemd (aktif/enabled) yang menjalankan bot dari folder ini,
# mis. fourtisbot.service — harus dimatikan sebelum PM2 start.
legacy_units() {
    command -v systemctl >/dev/null || return 0
    local u wd exec_start pid
    {
        while read -r u _; do
            [[ "$u" == *.service && "$u" != pm2-* ]] || continue
            wd="$(systemctl show -p WorkingDirectory --value "$u" 2>/dev/null || true)"
            exec_start="$(systemctl show -p ExecStart --value "$u" 2>/dev/null || true)"
            if [ "${wd%/}" = "$BOT_DIR" ] || [[ "$exec_start" == *"$BOT_DIR/"* || "$exec_start" == *"$BOT_DIR "* ]]; then
                echo "$u"
            fi
        done < <(systemctl list-units --type=service --all --no-legend --plain 2>/dev/null || true)
        # Paling akurat: unit yang memegang proses bot yang sedang jalan,
        # apa pun bentuk ExecStart-nya.
        for pid in $(bot_pids); do
            unit_from_cgroup "/proc/$pid/cgroup"
        done
    } | sort -u | while read -r u; do
        [ -n "$u" ] || continue
        systemctl is-active --quiet "$u" 2>/dev/null || systemctl is-enabled --quiet "$u" 2>/dev/null || continue
        echo "$u"
    done
}

# Nama unit systemd dari file cgroup sebuah proses (cgroup v1 & v2).
# Kosong kalau proses tidak dijalankan unit sistem (SSH, PM2 dikecualikan).
unit_from_cgroup() {
    local line path unit
    [ -r "$1" ] || return 0
    while IFS= read -r line; do
        path="${line#*:*:}"
        if [[ "$path" =~ ^/system\.slice/([^/]+\.service) ]]; then
            unit="${BASH_REMATCH[1]}"
            [[ "$unit" == pm2-* ]] || echo "$unit"
            return 0
        fi
    done <"$1"
    return 0
}

# Environment= dari unit systemd ikut dibawa ke PM2 (mis. PLAYWRIGHT_BROWSERS_PATH)
import_unit_env() {
    local kv
    for kv in $(systemctl show -p Environment --value "$1" 2>/dev/null || true); do
        [[ "$kv" == *=* ]] || continue
        case "${kv%%=*}" in PATH|HOME|USER|LOGNAME|SHELL|PWD) continue ;; esac
        export "${kv?}"
        log "Bawa env dari $1: ${kv%%=*}"
    done
}

# status<TAB>restart_count dari PM2 (kosong kalau app belum ada)
pm2_info() {
    pm2 jlist 2>/dev/null | "$PY" -c '
import json, sys
raw = sys.stdin.read()
try:
    apps = json.loads(raw[raw.index("["):])
except Exception:
    sys.exit(0)
for app in apps:
    if app.get("name") == sys.argv[1]:
        env = app.get("pm2_env", {})
        print("%s\t%s" % (env.get("status", ""), env.get("restart_time", 0)))
        break
' "$APP_NAME" || true
}

backup_runtime() {
    local f
    mkdir -p "$BACKUP_DIR/runtime"
    for f in "${RUNTIME_FILES[@]}"; do
        [ -e "$BOT_DIR/$f" ] || continue
        if [ "$f" = scans.db ]; then
            # backup API SQLite: salinan konsisten walau bot sedang menulis
            "$PY" -c 'import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()' "$BOT_DIR/$f" "$BACKUP_DIR/runtime/$f" \
                || cp -a "$BOT_DIR/$f" "$BACKUP_DIR/runtime/$f"
        else
            cp -a "$BOT_DIR/$f" "$BACKUP_DIR/runtime/$f"
        fi
    done
    log "Backup data runtime → $BACKUP_DIR/runtime"
}

# Kembalikan file runtime yang disentuh git (di-track di salah satu revisi).
# File yang tidak pernah di-track dibiarkan — bot masih menulis ke sana.
restore_runtime() {
    local f rev tracked
    for f in "${RUNTIME_FILES[@]}"; do
        [ -e "$BACKUP_DIR/runtime/$f" ] || continue
        tracked=0
        for rev in "$@"; do
            [ -n "$rev" ] && git cat-file -e "$rev:$f" 2>/dev/null && tracked=1
        done
        if [ "$tracked" = 1 ]; then
            cp -a "$BACKUP_DIR/runtime/$f" "$BOT_DIR/$f"
            log "Pulihkan $f dari backup"
        fi
    done
    return 0
}

convert_to_git() {
    log "Folder belum berupa git repo — konversi sekali (backup penuh dulu)..."
    # Bot yang sedang jalan terus menulis file di folder ini → tar exit 1
    # ("file changed as we read it") itu wajar: file runtime sudah di-backup
    # konsisten di backup_runtime. Hanya exit >= 2 yang benar-benar gagal.
    local tar_rc=0
    tar -czf "$BACKUP_DIR/full-before-deploy.tgz" -C "$BOT_DIR" \
        --warning=no-file-changed --warning=no-file-shrank --warning=no-file-removed \
        --exclude=./venv --exclude=./.venv --exclude=./charts --exclude=./generated_pnl \
        --exclude=./ms-playwright --exclude=./node_modules --exclude='./__pycache__' . || tar_rc=$?
    [ "$tar_rc" -le 1 ] || die "Backup penuh gagal (tar exit $tar_rc) — deploy dibatalkan, tidak ada yang diubah."
    log "Backup penuh → $BACKUP_DIR/full-before-deploy.tgz"
    STAGE=code CONVERTED=1
    git -c init.defaultBranch="$BRANCH" init -q
    git remote add origin "$REPO_URL"
    git fetch -q origin "$BRANCH" || fail "git fetch gagal (cek koneksi internet server)"
    NEW="$(git rev-parse FETCH_HEAD)"
    git checkout -q -f -B "$BRANCH" "$NEW"
    git branch -q --set-upstream-to="origin/$BRANCH" "$BRANCH" 2>/dev/null || true
    restore_runtime "$NEW"
    log "Kode diganti dengan versi GitHub ($(git log -1 --format='%h %s'))."
}

update_git() {
    local path dirty=() f
    STAGE=code
    # File runtime yang di-track & berubah: sudah di-backup → kembalikan ke
    # versi git dulu supaya update tidak ditolak, lalu dipulihkan sesudahnya.
    while IFS= read -r path; do
        path="${path:3}"
        if [[ " ${RUNTIME_FILES[*]} " == *" $path "* ]]; then
            git checkout -q HEAD -- "$path"
        else
            dirty+=("$path")
        fi
    done < <(git status --porcelain --untracked-files=no)
    if [ ${#dirty[@]} -gt 0 ]; then
        restore_runtime "$OLD"
        die "Ada perubahan lokal di file kode (tidak ada di GitHub): ${dirty[*]}
    Deploy dibatalkan supaya perubahan itu tidak hilang. Pilih salah satu:
      • buang perubahan lokal : cd $BOT_DIR && git checkout -- ${dirty[*]}
      • atau commit perubahan itu ke GitHub dulu, lalu deploy lagi."
    fi
    if git show-ref -q --verify "refs/heads/$BRANCH" && ! git merge-base --is-ancestor "$BRANCH" "$NEW"; then
        restore_runtime "$OLD"
        die "Branch $BRANCH lokal punya commit yang tidak ada di GitHub. Selesaikan manual dulu."
    fi
    # File runtime yang belum di-track tapi di-track di versi baru akan
    # menghalangi checkout — sudah di-backup, singkirkan sebentar.
    for f in "${RUNTIME_FILES[@]}"; do
        if [ -e "$f" ] && ! git ls-files --error-unmatch "$f" >/dev/null 2>&1 \
            && git cat-file -e "$NEW:$f" 2>/dev/null; then
            rm -f "$f"
        fi
    done
    git checkout -q -B "$BRANCH" "$NEW"
    git branch -q --set-upstream-to="origin/$BRANCH" "$BRANCH" 2>/dev/null || true
    restore_runtime "$OLD" "$NEW"
    log "Kode diupdate: ${OLD:0:7} → ${NEW:0:7}"
}

pip_install() {
    local before after
    log "Install requirements.txt..."
    before="$("$PY" -m pip show playwright 2>/dev/null | awk '/^Version:/{print $2}' || true)"
    "$PY" -m pip install -q -r requirements.txt || return 1
    after="$("$PY" -m pip show playwright 2>/dev/null | awk '/^Version:/{print $2}' || true)"
    # Versi Playwright baru butuh browser Chromium yang cocok, kalau tidak
    # semua chart gagal di-render.
    if [ -n "$after" ] && [ "$before" != "$after" ]; then
        log "Playwright $before → $after: install browser Chromium..."
        "$PY" -m playwright install chromium || warn "playwright install chromium gagal — chart bisa error"
    fi
}

smoke_test() {
    "$PY" -m py_compile ./*.py >"$BACKUP_DIR/smoke.log" 2>&1 \
        && timeout 180 "$PY" -c 'import telegram_bot
from telegram.ext import JobQueue
JobQueue()' >>"$BACKUP_DIR/smoke.log" 2>&1
}

# Proses bot dari folder ini yang jalan di luar PM2 (manual/nohup/run_bot.sh)
# = instance kedua → harus dihentikan sebelum PM2 start.
stop_stray_bots() {
    local pm2_pid pids pid parent
    pm2_pid="$(pm2 pid "$APP_NAME" 2>/dev/null || true)"
    pids="$(bot_pids | grep -vx "${pm2_pid:-0}" || true)"
    [ -z "$pids" ] && return 0
    warn "Hentikan proses bot di luar PM2 (cegah 409 Conflict): $(tr '\n' ' ' <<<"$pids")"
    for pid in $pids; do
        parent="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
        if [ -n "$parent" ] && [[ "$(ps -o args= -p "$parent" 2>/dev/null || true)" == *run_bot.sh* ]]; then
            kill "$parent" 2>/dev/null || true   # loop auto-restart run_bot.sh
        fi
        kill "$pid" 2>/dev/null || true
    done
    KILLED_STRAYS=1
    for _ in $(seq 1 15); do
        sleep 1
        pids="$(bot_pids | grep -vx "${pm2_pid:-0}" || true)"
        [ -z "$pids" ] && return 0
    done
    # shellcheck disable=SC2086  # sengaja di-split: satu argumen per PID
    kill -9 $pids 2>/dev/null || true
}

warn_other_bots() {
    local pid cwd
    for pid in $(pgrep -f 'telegram_bot\.py' || true); do
        cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
        if [ -n "$cwd" ] && [ "$cwd" != "$BOT_DIR" ]; then
            warn "Ada bot lain jalan dari $cwd (PID $pid). Kalau token Telegram-nya sama, matikan — dua bot satu token = 409 Conflict."
        fi
    done
    return 0
}

start_pm2() {
    local f
    LOG_DIR="${PM2_HOME:-$HOME/.pm2}/logs"
    ERR_LOG="$LOG_DIR/${APP_NAME}-error.log"
    OUT_LOG="$LOG_DIR/${APP_NAME}-out.log"
    declare -gA LOG_OFFSET=()
    for f in "$ERR_LOG" "$OUT_LOG"; do
        LOG_OFFSET[$f]="$(stat -c %s "$f" 2>/dev/null || echo 0)"
    done
    PM2_TOUCHED=1
    # delete + start (bukan restart) supaya perubahan ecosystem.config.js ikut terpakai
    pm2 delete "$APP_NAME" >/dev/null 2>&1 || true
    log "Start bot di PM2..."
    pm2 start "$BOT_DIR/ecosystem.config.js" --only "$APP_NAME" >/dev/null
}

new_logs() {
    local f off size
    for f in "$ERR_LOG" "$OUT_LOG"; do
        [ -f "$f" ] || continue
        off="${LOG_OFFSET[$f]:-0}"
        size="$(stat -c %s "$f")"
        [ "$size" -lt "$off" ] && off=0
        tail -c +"$((off + 1))" "$f"
    done
    return 0
}

health_check() {
    # restart_time selalu 0 setelah delete + start; naik = bot crash
    local start=$SECONDS started_at=-1 status restarts base=0 logs
    log "Health check (maks ${HEALTH_TIMEOUT}s)..."
    sleep 2
    while (( SECONDS - start < HEALTH_TIMEOUT )); do
        IFS=$'\t' read -r status restarts < <(pm2_info) || true
        case "$status" in
            errored|stopped|"waiting restart")
                HEALTH_REASON="status PM2: $status"; return 1 ;;
        esac
        if [[ "${restarts:-}" =~ ^[0-9]+$ ]] && [ "$restarts" -gt "$base" ]; then
            HEALTH_REASON="bot crash dan di-restart PM2"; return 1
        fi
        logs="$(new_logs)"
        if [[ "$logs" == *"409 CONFLICT"* ]]; then
            HEALTH_REASON="409 Conflict — ada instance bot lain dengan token yang sama"; return 1
        fi
        if [[ "$logs" == *"Bot crash dengan error fatal"* || "$logs" == *"Please set your Telegram bot token"* ]]; then
            HEALTH_REASON="bot error saat start (token/koneksi Telegram?)"; return 1
        fi
        if [ "$started_at" -lt 0 ] && [[ "$logs" == *"Application started"* ]]; then
            started_at=$SECONDS
            log "Bot terhubung ke Telegram, cek stabil ${STABLE_SECS}s..."
        fi
        if [ "$started_at" -ge 0 ] && [ "$status" = online ] && (( SECONDS - started_at >= STABLE_SECS )); then
            return 0
        fi
        sleep 2
    done
    HEALTH_REASON="bot tidak mengonfirmasi start dalam ${HEALTH_TIMEOUT}s"
    return 1
}

ensure_pm2_startup() {
    command -v systemctl >/dev/null || return 0
    local user
    user="$(id -un)"
    if ! systemctl is-enabled --quiet "pm2-$user" 2>/dev/null; then
        log "Aktifkan PM2 auto-start saat server reboot..."
        if pm2 startup systemd -u "$user" --hp "$HOME" >/dev/null 2>&1; then
            pm2 save >/dev/null
        else
            warn "pm2 startup gagal — jalankan manual: pm2 startup && pm2 save"
        fi
    fi
}

prune_backups() {
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -r \
        | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -rf || true
    return 0
}

fail() {
    [ "${STAGE:-precheck}" = precheck ] && die "$1"
    rollback "$1"
}

rollback() {
    trap - ERR
    set +e
    warn "Deploy gagal: $1"
    warn "ROLLBACK ke kondisi sebelum deploy..."
    if [ "$CONVERTED" = 1 ]; then
        rm -rf "$BOT_DIR/.git"
        tar -xzf "$BACKUP_DIR/full-before-deploy.tgz" -C "$BOT_DIR"
        log "Kode dikembalikan dari backup penuh."
    elif [ -n "$OLD" ] && [ "$STAGE" != precheck ]; then
        git checkout -q -f --detach "$OLD"
        if [ -n "$ORIG_MAIN" ]; then
            git branch -q -f "$BRANCH" "$ORIG_MAIN"
        fi
        [ -n "$ORIG_BRANCH" ] && git checkout -q -f "$ORIG_BRANCH"
        restore_runtime "$OLD" "$NEW"
        log "Kode dikembalikan ke ${OLD:0:7}."
    fi
    if [ "$STAGE" = process ]; then
        if [ ${#MIGRATED_UNITS[@]} -gt 0 ]; then
            pm2 delete "$APP_NAME" >/dev/null 2>&1
            pm2 save --force >/dev/null 2>&1
            for u in "${MIGRATED_UNITS[@]}"; do
                systemctl enable --quiet "$u" 2>/dev/null
                systemctl start "$u" && log "Bot kembali jalan lewat systemd $u."
            done
        elif [ "$PM2_TOUCHED" = 1 ] || [ "$KILLED_STRAYS" = 1 ]; then
            pm2 delete "$APP_NAME" >/dev/null 2>&1
            pm2 start "$BOT_DIR/ecosystem.config.js" --only "$APP_NAME" >/dev/null 2>&1 \
                && pm2 save >/dev/null 2>&1 && log "Bot versi lama dijalankan lagi di PM2."
        fi
        if [ -n "${ERR_LOG:-}" ]; then
            warn "Log bot terakhir:"
            new_logs | tail -n 25 >&2
        fi
    fi
    [ -n "$BACKUP_DIR" ] && warn "Backup data: $BACKUP_DIR"
    die "Deploy dibatalkan. Kirim pesan error di atas ke developer."
}

main "$@"
