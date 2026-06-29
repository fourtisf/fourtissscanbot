import re
from typing import Optional, Tuple

def detect_pair_address(text: str) -> Optional[Tuple[str, str]]:
    """
    Mendeteksi alamat pair hanya dari URL DexScreener.

    Mengembalikan (address, chain_id) jika URL ditemukan,
    atau None jika tidak.
    """
    text = text.strip()

    # Regex untuk mendeteksi alamat pair DexScreener dari URL
    # Contoh: https://dexscreener.com/base/0x352b850b733ab8bab50aed1dab5d22e3186ce984
    # ✅ PERBAIKAN: Regex untuk mendukung semua chain
    dex_url_pattern = r'https?://dexscreener\.com/(\w+)/([\w]+)'
    match = re.search(dex_url_pattern, text)
    if match:
        chain_id = match.group(1)
        address = match.group(2)
        return address, chain_id

    return None