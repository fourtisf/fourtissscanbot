// PM2 config untuk FourtisScanBot.
//
// Deploy / update (cara yang disarankan — backup, update, restart, rollback otomatis):
//   bash /root/botscan/deploy.sh
//
// Manual (dari dalam folder bot):
//   pm2 start ecosystem.config.js
//   pm2 save
//
// CATATAN: pilih HANYA SATU process manager. Kalau pakai PM2, JANGAN
// sekaligus pakai systemd untuk bot yang sama — dua-duanya jalan = dua
// instance = error "Conflict" dari Telegram = bot mati. deploy.sh otomatis
// mematikan unit systemd lama saat pindah ke PM2.
const fs = require("fs");
const path = require("path");

// Interpreter Python: BOT_PYTHON (diisi deploy.sh) → venv di folder bot → python3.
function pickPython() {
  if (process.env.BOT_PYTHON) return process.env.BOT_PYTHON;
  for (const dir of ["venv", ".venv"]) {
    const candidate = path.join(__dirname, dir, "bin", "python");
    if (fs.existsSync(candidate)) return candidate;
  }
  return "python3";
}

module.exports = {
  apps: [
    {
      name: "botscan",
      script: path.join(__dirname, "telegram_bot.py"),
      interpreter: pickPython(),

      // Jalankan dari folder tempat file ini berada (folder bot).
      cwd: __dirname,

      // Tanpa ini output print() Python tertahan buffer dan telat muncul di pm2 logs.
      env: { PYTHONUNBUFFERED: "1" },

      // Auto-restart kalau proses mati.
      autorestart: true,
      restart_delay: 5000,      // jeda 5 detik sebelum restart
      max_restarts: 50,         // jangan cepat menyerah

      // Restart otomatis SEBELUM kehabisan RAM (anti-OOM). Sesuaikan dengan
      // RAM server; 600M aman untuk VPS kecil dengan render chart Chromium.
      max_memory_restart: "600M",

      // Beri waktu bot berhenti rapi saat restart.
      kill_timeout: 8000,

      // Jangan restart karena file berubah (bot ini menulis banyak file).
      watch: false,
    },
  ],
};
