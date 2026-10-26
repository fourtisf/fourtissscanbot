"""Konfigurasi utama ada di bot_config.py (satu sumber). File ini hanya re-export
supaya import lama `from config import Config` tetap jalan, plus daftar link trading."""
from bot_config import Config  # noqa: F401

SOL_BOT_TRADING = [
    ("AXI", "https://axiom.trade/@fourtis"),
    ("TRO", "https://t.me/paris_trojanbot?start=r-charliefourtis"),
    ("PHO", "https://photon-sol.tinyastro.io/@fourtis"),
    ("GM",  "https://gmgn.ai/r/25JyIYly"),
    ("BLO", "https://t.me/BloomSolana_bot?start=ref_fourtis"),
    ("MAE", "https://t.me/maestro?start=r-charliefourtis"),
    ("BAN", "https://t.me/BananaGun_bot?start=ref_fourtisbot"),
]
