import json
import os
import copy
import threading
from datetime import datetime, timezone
import aiohttp
import asyncio

STATS_FILE = "stats.json"
BACKUP_FILE = "stats_backup.json"
AUTHORIZED_USER = 5231963014  # user yang menerima report

# Lock untuk melindungi 'stats' dari akses bersamaan.
# save_stats() dijalankan via asyncio.to_thread() (thread lain) tiap 60 detik,
# sementara handler di event loop bisa memodifikasi 'stats' pada saat yang sama.
# Tanpa lock, json.dump() bisa crash: "dictionary changed size during iteration"
# dan file stats.json bisa rusak/terpotong.
_stats_lock = threading.Lock()

# ================= Stats default =================
stats = {
    "total_users": 0,
    "total_groups": 0,
    "scans_today": 0,
    "total_scans": 0,
    "users": [],
    "groups": [],
    "last_reset": None,
    "scans_by_chain": {
        "BSC": {"today": 0, "total": 0},
        "ETHEREUM": {"today": 0, "total": 0},
        "SOLANA": {"today": 0, "total": 0},
        "TRON": {"today": 0, "total": 0},
        "BASE": {"today": 0, "total": 0},
        "UNKNOWN": {"today": 0, "total": 0}  # Tambahkan ini untuk melacak token yang tidak teridentifikasi
    }
}


# ================= Load / Save =================
def load_stats():
    global stats
    loaded = False
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r") as f:
                stats = json.load(f)
                loaded = True
        elif os.path.exists(BACKUP_FILE):
            with open(BACKUP_FILE, "r") as f:
                stats = json.load(f)
                loaded = True
    except Exception as e:
        print(f"[WARN] load_stats gagal: {e}")
        if os.path.exists(BACKUP_FILE):
            with open(BACKUP_FILE, "r") as f:
                stats = json.load(f)
                loaded = True

    # --- Data Migration and Cleanup ---
    if loaded and "scans_by_chain" in stats:
        cleaned_chains = {}
        for chain, data in stats["scans_by_chain"].items():
            chain_upper = chain.upper()  # normalize casing

            if "ETHEREUM" in chain_upper or chain_upper == "ETH":
                final_chain = "ETHEREUM"
            elif "BSC" in chain_upper:
                final_chain = "BSC"
            elif "SOLANA" in chain_upper or chain_upper == "SOL":
                final_chain = "SOLANA"
            elif "TRON" in chain_upper:
                final_chain = "TRON"
            elif "BASE" in chain_upper:
                final_chain = "BASE"
            elif "SYMBOL" in chain_upper or "UNKNOWN" in chain_upper:
                final_chain = "UNKNOWN"
            else:
                final_chain = chain_upper  # biar konsisten uppercase

            # Merge data ke key final
            if final_chain not in cleaned_chains:
                cleaned_chains[final_chain] = {"today": 0, "total": 0}

            cleaned_chains[final_chain]["today"] += data.get("today", 0)
            cleaned_chains[final_chain]["total"] += data.get("total", 0)

        stats["scans_by_chain"] = cleaned_chains

    # Pastikan semua key wajib ada supaya handler/status tidak KeyError
    # kalau stats.json lama tidak lengkap atau sebagian rusak.
    stats.setdefault("total_users", 0)
    stats.setdefault("total_groups", 0)
    stats.setdefault("scans_today", 0)
    stats.setdefault("total_scans", 0)
    stats.setdefault("users", [])
    stats.setdefault("groups", [])
    stats.setdefault("last_reset", None)
    stats.setdefault("scans_by_chain", {})

    # Ensure all default chains exist
    default_chains = {
        "BSC": {"today": 0, "total": 0},
        "ETHEREUM": {"today": 0, "total": 0},
        "SOLANA": {"today": 0, "total": 0},
        "TRON": {"today": 0, "total": 0},
        "BASE": {"today": 0, "total": 0},
        "UNKNOWN": {"today": 0, "total": 0},
    }
    for chain, data in default_chains.items():
        if chain not in stats["scans_by_chain"]:
            stats["scans_by_chain"][chain] = data

    save_stats()



def save_stats():
    global stats
    if not stats:
        print("[WARN] Stats kosong, skip save")
        return
    try:
        # Ambil snapshot di bawah lock supaya tidak ada thread lain yang
        # memodifikasi 'stats' selagi kita menulisnya (anti "changed size
        # during iteration" & anti file terpotong).
        with _stats_lock:
            snapshot = copy.deepcopy(stats)

        payload = json.dumps(snapshot, indent=2, sort_keys=True)

        # Tulis atomik: tulis ke file sementara lalu rename, supaya kalau
        # proses mati di tengah penulisan, file lama tidak ikut rusak.
        for target in (STATS_FILE, BACKUP_FILE):
            tmp = f"{target}.tmp"
            with open(tmp, "w") as f:
                f.write(payload)
            os.replace(tmp, target)
    except Exception as e:
        print(f"[WARN] Gagal save stats: {e}")


# ================= Chain Detection =================
# ================= Chain Detection =================
async def detect_chain_from_address(address: str) -> str:
    """Mendeteksi blockchain token menggunakan Dexscreener API"""
    if not address:
        return "UNKNOWN"

    url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
    try:
        # Timeout wajib: tanpa ini, kalau API menggantung, handler ikut hang
        # tanpa batas dan bot terlihat "mati" walau proses masih hidup.
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        # ambil chainId mentah dari DexScreener
                        chain_api = str(pairs[0].get("chainId", "")).lower().strip()

                        # Map DexScreener chainId (string/angka) ke nama standar
                        chain_map = {
                            "ethereum": "ETHEREUM", "1": "ETHEREUM",
                            "bsc": "BSC", "56": "BSC",
                            "solana": "SOLANA", "101": "SOLANA",
                            "tron": "TRON", "111": "TRON",
                            "base": "BASE", "8453": "BASE",
                        }

                        if chain_api in chain_map:
                            result = chain_map[chain_api]
                            print(f"[DEBUG] DexScreener chainId={chain_api} -> {result}")
                            return result
                        else:
                            # catch-all logging untuk chain baru
                            print(f"[DEBUG] Unmapped chainId dari DexScreener: {chain_api}")
                            return "UNKNOWN"
    except Exception as e:
        print(f"[WARN] detect_chain_from_address failed: {e}")

    # fallback deteksi dari pola address kalau DexScreener gagal
    if address.startswith("0x") and len(address) == 42:
        return "ETHEREUM"
    elif address.startswith("T") and len(address) == 34:
        return "TRON"
    elif 32 <= len(address) <= 44 and not address.startswith(("0x", "T")):
        return "SOLANA"

    return "UNKNOWN"




# ================= Tracker =================
def track_chat(chat):
    """Tambah chat (user / group) ke database"""
    global stats
    chat_id = chat.id
    # Lock hanya di sekitar mutasi (cepat). save_stats() dipanggil di luar lock
    # supaya tidak deadlock (threading.Lock tidak reentrant).
    with _stats_lock:
        if chat.type in ("group", "supergroup", "channel"):
            if chat_id not in stats["groups"]:
                stats["groups"].append(chat_id)
                stats["total_groups"] += 1
        else:
            if chat_id not in stats["users"]:
                stats["users"].append(chat_id)
                stats["total_users"] += 1
    save_stats()


async def track_scan(token_address: str = None, chain: str = None):
    """Add scan counter per blockchain (async)"""
    global stats

    if not chain and token_address:
        chain = await detect_chain_from_address(token_address)
        print(f"[DEBUG] Detected chain for {token_address}: {chain}")
    if not chain:
        chain = "UNKNOWN"

    chain = chain.upper()

    with _stats_lock:
        if chain not in stats["scans_by_chain"]:
            stats["scans_by_chain"][chain] = {"today": 0, "total": 0}

        stats["scans_by_chain"][chain]["today"] += 1
        stats["scans_by_chain"][chain]["total"] += 1

        stats["scans_today"] += 1
        stats["total_scans"] += 1
        today_count = stats["scans_by_chain"][chain]["today"]
        total_count = stats["scans_by_chain"][chain]["total"]

    print(f"[DEBUG] Tracked scan: {chain} - Today: {today_count}, Total: {total_count}")
    save_stats()


def track_scan_sync(token_address=None, chain=None):
    """Wrapper sinkron untuk track_scan async"""
    asyncio.run(track_scan(token_address=token_address, chain=chain))


# ================= Status Message =================
DEFAULT_CHAINS = ["TRON", "BASE", "ETHEREUM", "BSC", "SOLANA"]

def get_status_message():
    time_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def get_chain_emoji(chain):
        emoji_map = {
            "ETHEREUM": "🔷 ETHEREUM",
            "BSC": "🟡 BSC",
            "SOLANA": "🟣 SOLANA",
            "BASE": "🔵 BASE",
            "TRON": "🔴 TRON",
            "UNKNOWN": "$SYMBOL"
        }
        return emoji_map.get(chain, chain)

    # 🟢 Today impressions
    chain_today_msg = "\n".join([
        f"  {get_chain_emoji(chain)} Today: {stats['scans_by_chain'][chain]['today']}"
        for chain in DEFAULT_CHAINS
        if chain in stats["scans_by_chain"]
    ])

    # 🚀 Total impressions
    chain_total_msg = "\n".join([
        f"  {get_chain_emoji(chain)} Total: {stats['scans_by_chain'][chain]['total']}"
        for chain in DEFAULT_CHAINS
        if chain in stats["scans_by_chain"]
    ])

    # ⚡️ Hitung total semua chain (tanpa UNKNOWN)
    total_impressions = sum(
        data['total']
        for chain, data in stats["scans_by_chain"].items()
        if chain in DEFAULT_CHAINS
    )

    return (
        f"🤖<b><a href='https://t.me/FourtisScan'>Fourtis LIVE</a></b>\n\n"
        f"👥 <b>Users:</b> {stats['total_users']} | <b>Groups:</b> {stats['total_groups']}\n"
        f"🔎 <b>Scans Today:</b> {stats['scans_today']} | ⚡ <b>Actions:</b> {stats['scans_today']}\n"
        f"📈 <b>Total Scans:</b> {stats['total_scans']}\n\n"
        f"🟢<b>Scans by Blockchain (Today):</b>\n{chain_today_msg}\n\n"
        f"🚀<b>Total Impressions:</b>\n{chain_total_msg}\n\n"
        f"⚡️<b>All Chains Total Impressions:</b> {total_impressions}\n"
        f"🕒 <i>{time_now}</i>"
    )



# ================= Reset Harian =================
def reset_daily_stats():
    """Reset scans_today dan scans per chain (today) setiap hari UTC 00:00"""
    global stats
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if stats.get("last_reset") != today_str:
        stats["scans_today"] = 0
        for chain in stats["scans_by_chain"]:
            stats["scans_by_chain"][chain]["today"] = 0
        stats["last_reset"] = today_str
        save_stats()
        print(f"[INFO] Reset daily stats at {today_str}")


# ================= Broadcast Status =================
async def send_status(bot):
    """Kirim status message ke AUTHORIZED_USER"""
    msg = get_status_message()
    try:
        await bot.send_message(
            chat_id=AUTHORIZED_USER,
            text=msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"[WARN] Gagal kirim status message: {e}")


# ================= Inisialisasi =================
load_stats()