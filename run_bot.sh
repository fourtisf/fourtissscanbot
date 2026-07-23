#!/usr/bin/env bash
#
# run_bot.sh — menjalankan FourtisScanBot dengan AUTO-RESTART.
#
# Kenapa perlu ini?
#   Kalau proses Python mati (crash, OOM, host restart), tidak ada yang
#   menghidupkannya lagi → bot "berhenti running". Script ini otomatis
#   menjalankan ulang bot kalau berhenti, dengan jeda yang naik bertahap.
#
# PENTING: HANYA jalankan SATU proses bot untuk satu token Telegram.
#   Dua proses dengan token yang sama = error "Conflict" dari Telegram
#   dan bot bisa mati sendiri. Script di bawah memastikan hanya satu
#   instance yang jalan (pakai lock file).
#
# Pemakaian:
#   chmod +x run_bot.sh
#   ./run_bot.sh
#
set -u

cd "$(dirname "$0")" || exit 1

LOCK_FILE="/tmp/fourtisscanbot.lock"

# Cegah instance ganda (penyebab Conflict). flock akan gagal kalau
# sudah ada proses lain yang memegang lock.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "❌ Bot sudah berjalan (lock: $LOCK_FILE). Batalkan start kedua."
    exit 1
fi

# Pilih interpreter: pakai venv kalau ada.
if [ -x "venv/bin/python" ]; then
    PY="venv/bin/python"
else
    PY="python3"
fi

BACKOFF=5
MAX_BACKOFF=300

while true; do
    echo "🚀 [$(date '+%Y-%m-%d %H:%M:%S')] Menjalankan bot..."
    "$PY" telegram_bot.py
    EXIT_CODE=$?

    # Exit code 0 atau 130 (Ctrl+C) = berhenti disengaja → keluar.
    if [ "$EXIT_CODE" -eq 0 ] || [ "$EXIT_CODE" -eq 130 ]; then
        echo "🛑 Bot berhenti normal (exit $EXIT_CODE). Keluar."
        break
    fi

    echo "💥 [$(date '+%Y-%m-%d %H:%M:%S')] Bot mati (exit $EXIT_CODE). Restart dalam ${BACKOFF}s..."
    sleep "$BACKOFF"
    BACKOFF=$(( BACKOFF * 2 ))
    if [ "$BACKOFF" -gt "$MAX_BACKOFF" ]; then
        BACKOFF=$MAX_BACKOFF
    fi
done
