# promo_manager.py
import json
import os
import asyncio
from datetime import datetime

REPORT_FILE = os.path.join(os.path.dirname(__file__), "promo.json")


# ----------------------------
# Helper baca/tulis file (aman & atomik)
# ----------------------------
def _read_promos() -> dict:
    if not os.path.exists(REPORT_FILE):
        return {}
    try:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"DEBUG: Failed to read promo.json: {e}")
        return {}


def _write_promos(data: dict) -> None:
    try:
        tmp = REPORT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, REPORT_FILE)  # atomik, cegah file rusak
    except Exception as e:
        print(f"DEBUG: Failed to write promo.json: {e}")


# ----------------------------
# Add a global promo with expiry
# ----------------------------
async def add_report(text: str, expiry: datetime) -> str:
    data = await asyncio.to_thread(_read_promos)

    promos = data.get("global", [])
    promos.append({
        "text": text,
        "expiry": expiry.isoformat()
    })
    data["global"] = promos

    await asyncio.to_thread(_write_promos, data)
    return "✅ Promo added."


# ----------------------------
# Reset all promos
# ----------------------------
async def reset_reports() -> str:
    def _remove():
        try:
            if os.path.exists(REPORT_FILE):
                os.remove(REPORT_FILE)
                print("DEBUG: promo.json removed")
        except Exception as e:
            print(f"DEBUG: Failed to remove promo.json: {e}")

    await asyncio.to_thread(_remove)
    return "✅ All promos have been reset."


# ----------------------------
# Get all global promos (filter expired)
# ----------------------------
async def get_custom_report() -> str:
    data = await asyncio.to_thread(_read_promos)
    if not data:
        return ""

    now = datetime.utcnow()
    valid_promos = []
    updated_promos = []
    changed = False

    for promo in data.get("global", []):
        expiry_raw = promo.get("expiry")
        # Entri rusak (tanpa expiry / format salah) TIDAK boleh membuat
        # seluruh laporan token crash — cukup lewati entri itu.
        try:
            expiry = datetime.fromisoformat(expiry_raw) if expiry_raw else None
        except (ValueError, TypeError):
            expiry = None

        if expiry is None:
            changed = True  # buang entri rusak
            continue

        if expiry > now:
            valid_promos.append(promo.get("text", ""))
            updated_promos.append(promo)
        else:
            changed = True  # expired → dibuang

    # Hanya tulis ulang kalau memang ada perubahan → kurangi I/O di hot path
    # dan hindari race menulis file pada tiap scan.
    if changed:
        data["global"] = updated_promos
        await asyncio.to_thread(_write_promos, data)

    return "\n".join(p for p in valid_promos if p)
