# FourtisScanBot

Telegram bot untuk cek harga & scan kontrak crypto (ETH, BSC, Solana, Base, Tron).

---

## ⚠️ Kenapa bot sering "berhenti running"? (Penyebab & Perbaikan)

Bot ini beberapa kali mati sendiri. Setelah kode ditelusuri menyeluruh,
ini akar masalahnya dan apa yang sudah diperbaiki:

| # | Penyebab bot mati | Perbaikan |
|---|-------------------|-----------|
| 1 | **Chromium menumpuk saat render chart** — tiap `/c` menjalankan 1 browser headless (RAM besar) dan ditahan 35 detik. Kalau banyak yang pakai bersamaan, RAM habis → server meng-OOM-kill proses. | Dibatasi **1 browser dalam satu waktu** (semaphore), browser **selalu ditutup** walau error, dan waktu tunggu diturunkan (bisa diatur via env). |
| 2 | **Tidak ada auto-restart** — kalau proses mati (crash/OOM/reboot), tidak ada yang menghidupkan lagi, jadi bot tetap mati. | Ditambah **supervisor**: `run_bot.sh`, unit **systemd**, dan loop restart di dalam program. |
| 3 | **Token bot ter-commit di `.env`** (ada di riwayat git). Kalau bocor, orang lain bisa menjalankan bot dengan token yang sama → error **Conflict** dari Telegram → bot mati. | `.env` **dihapus dari git** & masuk `.gitignore`. Disediakan `.env.example`. Error Conflict kini ditangani (tidak crash) + peringatan jelas. |
| 4 | **Tidak ada error handler global** — error di handler/job bisa lolos dan menghentikan polling. | Ditambah **`add_error_handler`** yang menangkap semua error, mencatat log lengkap, dan tidak membuat bot crash. |
| 5 | **File `stats.json` ditulis dari 2 tempat sekaligus** (thread background tiap 60 detik + event loop) → bisa crash `dictionary changed size during iteration` / file rusak. | Penulisan dibuat **thread-safe** (lock + snapshot + tulis atomik). |
| 6 | **`init_db()` bisa gagal saat import** kalau DB terkunci/rusak → seluruh bot gagal start. | `init_db()` dibungkus try/except agar import tidak pernah gagal. |
| 7 | **Bot BEKU (freeze), bukan crash** — panggilan berat (render gambar, query database, API tanpa timeout) jalan di dalam event loop → semua user tertahan, bot "hidup tapi diam". Auto-restart TIDAK menolong karena proses tidak mati. | **(a)** Semua panggilan berat (SQLite, render PIL, kompresi gambar, baca/tulis file) dipindah ke thread (`asyncio.to_thread`). **(b)** Semua panggilan API diberi **timeout**. **(c)** Ditambah **watchdog**: kalau loop beku > `WATCHDOG_TIMEOUT` detik, proses dipaksa restart. **(d)** Perbaikan **file descriptor bocor** saat kirim chart (mencegah "Too many open files"). |

> Setelah semua perbaikan ini, dua mode kegagalan tertutup:
> - **Crash** (proses mati) → supervisor **menghidupkan ulang** otomatis.
> - **Freeze** (proses hidup tapi beku) → **watchdog** memaksa restart.
>
> Jadi apa pun penyebabnya, bot **pulih sendiri** dan mencatat penyebabnya di log.

---

## 🔑 ATURAN PALING PENTING: hanya SATU instance!

Telegram **melarang dua proses** memakai token yang sama untuk polling.
Kalau ada dua (misalnya jalan di laptop dan di VPS bersamaan), keduanya akan
kena error **Conflict** dan bot bisa mati. Jadi:

- Jalankan bot **di satu tempat saja**.
- Kalau merasa token pernah bocor, **rotate token** di [@BotFather](https://t.me/BotFather)
  (`/revoke`) lalu update `.env`.

---

## 🚀 Cara Menjalankan

### 1. Install dependency
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # untuk render chart
```

### 2. Siapkan konfigurasi
```bash
cp .env.example .env
# lalu edit .env, isi TELEGRAM_BOT_TOKEN dan API key lain
```

### 3. Jalankan

**Cara cepat (dengan auto-restart):**
```bash
./run_bot.sh
```

**Cara produksi A — PM2 (kalau sudah pakai PM2):**
```bash
# dari dalam folder bot
pm2 start ecosystem.config.js   # atau: pm2 restart botscan (kalau sudah ada)
pm2 save                        # supaya nyala lagi otomatis saat reboot
pm2 logs botscan                # lihat log real-time
```

**Cara produksi B — systemd (kalau TIDAK pakai PM2):**
```bash
# sesuaikan path & user di dalam file dulu
sudo cp fourtisscanbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fourtisscanbot
sudo systemctl status fourtisscanbot        # cek status
sudo journalctl -u fourtisscanbot -f         # lihat log real-time
```

> ⚠️ **Pilih SATU saja** (PM2 **atau** systemd **atau** run_bot.sh). Menjalankan
> lebih dari satu untuk token yang sama = dua instance = error **Conflict** =
> bot mati. Ini penyebab umum bot berhenti sendiri.

---

## ⚙️ Env untuk hemat resource (opsional)

Kalau server RAM kecil dan bot pernah kena OOM, atur di `.env`:

```
MAX_CONCURRENT_CHARTS=1     # jumlah chart yang boleh render bersamaan
CHART_RENDER_WAIT_MS=15000  # lama tunggu chart render (ms)
WATCHDOG_TIMEOUT=120        # detik; kalau loop beku selebihnya → paksa restart
```

---

## 📂 Struktur singkat

- `telegram_bot.py` — entry point bot (jalankan file ini).
- `main.py` — logika harga/chart/scan (DexScreener dll).
- `pnl_manager.py`, `leaderboard.py`, `stats_manager.py` — fitur PNL/leaderboard/statistik.
- `chart_renderer.py` — screenshot chart via Playwright/Chromium.
- `run_bot.sh`, `fourtisscanbot.service` — cara menjalankan dengan auto-restart.
