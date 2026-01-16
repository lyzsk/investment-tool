"""
Fetch Chinese holiday data from https://github.com/NateScarlet/holiday-cn
and save as JSON files for Java resource loading.

Usage:
    cd investment-tool/scripts
    python fetch_holidays_cn.py

Output:
    inv-common/src/main/resources/holiday/{year}.json
"""

import json
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌ Missing dependency: requests. Run: pip install requests")
    sys.exit(1)

# ================== CONFIG ==================
YEARS = list(range(2025, 2027))  # 2025, 2026
OUTPUT_DIR = Path("inv-common") / "src" / "main" / "resources" / "holiday"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json"
TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds


# ============================================

def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output directory: {OUTPUT_DIR.resolve()}")


def is_file_recent(file_path: Path, max_age_days: int = 365) -> bool:
    """Check if file exists and was modified within max_age_days."""
    if not file_path.exists():
        return False
    mtime = file_path.stat().st_mtime
    age_days = (time.time() - mtime) / (24 * 3600)
    return age_days < max_age_days


def fetch_year_data(year: int) -> dict | None:
    url = f"https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"  🌐 Attempt {attempt}/{MAX_RETRIES} via jsDelivr for {year}...")
            resp = requests.get(url, timeout=TIMEOUT)

            if resp.status_code == 404:
                print(f"  ℹ️  {year}.json not published yet (404). Skipping.")
                return None

            resp.raise_for_status()
            data = resp.json()

            # JSON 是 dict，节假日在 'days' 字段
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object (dict), got something else")

            if "days" not in data:
                raise ValueError("Missing 'days' field in JSON")

            days_list = data["days"]
            if not isinstance(days_list, list):
                raise ValueError("'days' field is not a list")

            holiday_map = {}
            for item in days_list:
                if not isinstance(item, dict) or "date" not in item or "isOffDay" not in item:
                    raise ValueError(f"Invalid item in {year}: {item}")
                holiday_map[item["date"]] = bool(item["isOffDay"])
            return holiday_map

        except Exception as e:
            print(f"  ⚠️  Failed (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ❌ All attempts failed for {year}.")
                return None
    return None


def save_json(data: dict, file_path: Path):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"  💾 Saved: {file_path.name}")


def main():
    print("🇨🇳 Fetching Chinese holiday data from holiday-cn...\n")
    ensure_output_dir()

    updated = 0
    for year in YEARS:
        file_path = OUTPUT_DIR / f"{year}.json"

        # Skip if recently downloaded (e.g., within 30 days)
        if is_file_recent(file_path, max_age_days=30):
            print(f"✅ {year}.json already exists and is recent. Skipping.")
            continue

        print(f"\n📥 Fetching {year}...")
        data = fetch_year_data(year)
        if data is not None:
            save_json(data, file_path)
            updated += 1
        else:
            print(f"⚠️  Skipped {year} due to errors.")

    print(f"\n🎉 Done! {updated} file(s) updated.")
    if updated == 0:
        print("ℹ️  All files are up-to-date or failed to fetch.")


if __name__ == "__main__":
    main()
