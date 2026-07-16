# promo_manager.py
import json
import os
from datetime import datetime

REPORT_FILE = os.path.join(os.path.dirname(__file__), "promo.json")

# ----------------------------
# Add a global promo with expiry
# ----------------------------
async def add_report(text: str, expiry: datetime) -> str:
    data = {}
    if os.path.exists(REPORT_FILE):
        try:
            with open(REPORT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"DEBUG: Failed to read promo.json: {e}")

    promos = data.get("global", [])
    promos.append({
        "text": text,
        "expiry": expiry.isoformat()
    })
    data["global"] = promos

    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"DEBUG: promo.json successfully updated")
    except Exception as e:
        print(f"DEBUG: Failed to write promo.json: {e}")

    return "✅ Promo added."

# ----------------------------
# Reset all promos
# ----------------------------
async def reset_reports() -> str:
    if os.path.exists(REPORT_FILE):
        os.remove(REPORT_FILE)
        print(f"DEBUG: promo.json removed")
    return "✅ All promos have been reset."

# ----------------------------
# Get all global promos (filter expired)
# ----------------------------
async def get_custom_report() -> str:
    if not os.path.exists(REPORT_FILE):
        return ""

    try:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"DEBUG: Failed to read promo.json: {e}")
        return ""

    now = datetime.utcnow()
    valid_promos = []
    updated_promos = []

    # Fungsi ini dipanggil di akhir SETIAP scan — satu entri promo yang rusak
    # (expiry bukan ISO format / key hilang / struktur salah) tidak boleh
    # bikin semua scan error.
    entries = data.get("global", []) if isinstance(data, dict) else []
    for promo in entries:
        try:
            expiry = datetime.fromisoformat(promo["expiry"])
            text = promo["text"]
            if not isinstance(text, str) or not text:
                raise ValueError("promo 'text' missing or not a string")
        except (KeyError, TypeError, ValueError) as e:
            print(f"DEBUG: Skipping malformed promo entry: {e}")
            continue
        if expiry > now:
            valid_promos.append(text)
            updated_promos.append(promo)

    # optional: remove expired promos
    try:
        data["global"] = updated_promos
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"DEBUG: Failed to rewrite promo.json: {e}")

    return "\n".join(valid_promos)
