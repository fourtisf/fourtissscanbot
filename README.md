# FourtisScanBot

Bot Telegram untuk scan harga & keamanan token di 5 blockchain (Ethereum, BSC, Solana, Base, Tron), dengan chart DexScreener, leaderboard PnL, dan Fear & Greed Index.

## Menjalankan bot

```bash
# 1. Siapkan environment (Python 3.11)
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. WAJIB: install browser untuk render chart.
#    Tanpa langkah ini semua chart DexScreener akan gagal dengan error umum.
#    PENTING: browser ter-install per-user. Kalau bot jalan lewat systemd
#    dengan User= yang berbeda, pakai path bersama (cocok dengan
#    Environment= di deploy/fourtissscanbot.service):
PLAYWRIGHT_BROWSERS_PATH=/opt/fourtissscanbot/ms-playwright playwright install chromium --with-deps

# 3. Konfigurasi token
cp .env.example .env
#    lalu edit .env dan isi TELEGRAM_BOT_TOKEN (dari @BotFather)

# 4. Jalankan
python telegram_bot.py
```

## Produksi (WAJIB pakai supervisor)

Jangan jalankan `python telegram_bot.py` langsung di SSH — begitu sesi ditutup
atau proses crash sekali, bot mati permanen. Pakai systemd:

```bash
sudo cp deploy/fourtissscanbot.service /etc/systemd/system/
# edit User= dan WorkingDirectory= sesuai server
sudo systemctl daemon-reload
sudo systemctl enable --now fourtissscanbot
journalctl -u fourtissscanbot -f   # lihat log
```

**Hanya boleh ada SATU instance bot yang polling.** Dua instance (atau orang
lain yang memegang token) menyebabkan error `409 Conflict` dan bot berhenti
menerima pesan tanpa crash — terlihat hidup tapi tidak menjawab.

## ⚠️ Migrasi satu kali di server (WAJIB dibaca sebelum `git pull`)

Branch ini MENGHAPUS `.env`, `scans.db`, `stats.json`, `stats_backup.json`,
`charts/`, dan `generated_pnl/` dari git (file-file ini sekarang di-ignore).
`git pull` pertama akan **menghapus file-file itu dari server** (atau konflik
kalau ada perubahan lokal). Lakukan ini SEKALI sebelum pull:

```bash
sudo systemctl stop fourtissscanbot          # atau matikan proses bot
cp .env scans.db stats.json stats_backup.json /tmp/bot-backup/   # backup KELUAR repo
git pull
cp /tmp/bot-backup/{.env,scans.db,stats.json,stats_backup.json} .  # restore
sudo systemctl start fourtissscanbot
```

Setelah ini, file-file tersebut tidak akan tersentuh git lagi.

## Keamanan token

- **Token yang sekarang dipakai masih ada di riwayat git** (`git show HEAD:.env`)
  dan repo sudah ter-push — anggap BOCOR. Setelah merge branch ini, **WAJIB
  revoke token via @BotFather dan ganti semua API key** di `.env` server.
  Meng-untrack file saja tidak menghapusnya dari riwayat.
- `.env` **tidak boleh** di-commit ke git. File ini sudah masuk `.gitignore`;
  token lama yang pernah ter-commit harus dianggap bocor.
- Kalau bot tiba-tiba berhenti menerima pesan, cek:
  ```bash
  curl "https://api.telegram.org/bot<TOKEN>/getMe"           # 401 = token di-revoke
  curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"  # url terisi = ada webhook/pembajakan
  ```
- Revoke token yang bocor lewat @BotFather → `/revoke`, lalu perbarui `.env`
  di server (bukan di git).

## Struktur data runtime

`scans.db`, `stats.json`, `stats_backup.json`, `charts/`, dan `generated_pnl/`
dibuat bot saat berjalan dan sengaja tidak dilacak git — jangan di-commit,
supaya `git pull` di server tidak menimpa data live.
