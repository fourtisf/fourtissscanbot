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

## Token pump.fun

Coin pump.fun yang masih di bonding curve sering belum di-index DexScreener
(dulu hasilnya "No results found"). Kalau DexScreener tidak menemukan alamat
Solana, bot otomatis mengambil data dari pump.fun (`pumpfun_api.py`):

1. **API pump.fun** (`frontend-api-v3.pump.fun`) — nama, MC, ATH, sosial.
   API ini tidak resmi dan di belakang Cloudflare, jadi bisa menolak IP server.
2. **Fallback on-chain** — membaca akun bonding curve langsung lewat Solana RPC
   (`SOL_RPC`, atau Helius via `HELIUS_API_KEY`, atau RPC publik). Report
   ditandai `Source: on-chain bonding curve` dan tanpa ATH/sosial.

Berlaku juga untuk tombol Chart (link ke chart pump.fun), `/scan`, `/pnl`, dan
leaderboard. Cek log `[pump.fun]` kalau datanya tidak muncul.

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
menerima pesan tanpa crash — terlihat hidup tapi tidak menjawab. **Pilih SATU
supervisor saja** (PM2 **atau** systemd **atau** `run_bot.sh`), jangan dua-duanya.

### Alternatif supervisor: PM2

```bash
pm2 start ecosystem.config.js   # atau: pm2 restart botscan (kalau sudah ada)
pm2 save                        # supaya nyala lagi otomatis saat reboot
pm2 logs botscan
```

## 🛡️ Ketahanan otomatis (sudah terpasang)

- **Webhook auto-delete saat start** — kalau ada webhook aktif, mode polling
  kena `409 Conflict` dan bot diam total. Bot kini menghapus webhook otomatis
  tiap start (`_post_init`), jadi masalah ini tidak terulang.
- **Watchdog anti-freeze** — kalau event loop beku > `WATCHDOG_TIMEOUT` detik,
  proses dipaksa keluar supaya supervisor me-restart. Untuk kasus "hidup tapi
  membeku" yang tidak bisa ditolong auto-restart biasa.
- **Supervisor loop internal** — kalau `run_polling` crash fatal, proses
  otomatis start ulang (backoff bertahap).

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
