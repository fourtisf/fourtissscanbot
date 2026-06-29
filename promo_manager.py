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

    for promo in data.get("global", []):
        expiry = datetime.fromisoformat(promo["expiry"])
        if expiry > now:
            valid_promos.append(promo["text"])
            updated_promos.append(promo)

    # optional: remove expired promos
    data["global"] = updated_promos
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return "\n".join(valid_promos)
