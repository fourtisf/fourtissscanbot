// PM2 config untuk FourtisScanBot.
//
// Pemakaian (dari dalam folder bot):
//   pm2 start ecosystem.config.js
//   pm2 save
//
// CATATAN: pilih HANYA SATU process manager. Kalau pakai PM2, JANGAN
// sekaligus pakai systemd untuk bot yang sama — dua-duanya jalan = dua
// instance = error "Conflict" dari Telegram = bot mati.
module.exports = {
  apps: [
    {
      name: "botscan",
      script: "telegram_bot.py",

      // Interpreter Python dari virtualenv (sesuaikan kalau path venv beda).
      interpreter: "./venv/bin/python",

      // Jalankan dari folder bot.
      cwd: "/root/botscan",

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
