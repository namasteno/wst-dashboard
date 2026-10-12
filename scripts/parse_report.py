"""
Parses the WGU "Marketing Daily Report" PDF and extracts WST's
Non-Funnel Daily Report rows (Inquiries, Intenders, App Complete).

Usage:
    python parse_report.py incoming/report.pdf data/daily.json

Appends any new dates found in the PDF to data/daily.json (skips
dates already present, so it's safe to re-run on the same file).
"""
import sys
import json
import re
from pathlib import Path
import pdfplumber

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

DATE_RE = re.compile(
    r"([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
)


def find_wst_rows(pdf_path):
    """
    Scan every table on every page for the 'Non - Funnel Daily Report'
    section and pull out each date row's WST columns (7th/8th/9th
    numeric group: WSB, LSH, WST, WSE each have 3 columns).
    """
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "Non - Funnel Daily Report" not in text and "Non-Funnel Daily Report" not in text:
                continue
            for line in text.split("\n"):
                m = DATE_RE.match(line.strip())
                if not m:
                    continue
                mon, day, year, _wd = m.groups()
                mon_num = MONTHS.get(mon.lower())
                if not mon_num:
                    continue
                # pull every number (including thousands separators) after the date/weekday
                rest = line[m.end():]
                nums = re.findall(r"[\d,]+", rest)
                nums = [int(n.replace(",", "")) for n in nums]
                # Expect 12 numbers: WSB(3) LSH(3) WST(3) WSE(3)
                if len(nums) < 9:
                    continue
                wst_inq, wst_int, wst_app = nums[6], nums[7], nums[8]
                date_str = f"{mon.title()} {int(day)}, {year}"
                rows.append({
                    "date": date_str,
                    "Inquiries": wst_inq,
                    "Intenders": wst_int,
                    "App Complete": wst_app,
                })
    return rows


def main():
    if len(sys.argv) != 3:
        print("Usage: parse_report.py <pdf_path> <daily_json_path>")
        sys.exit(1)

    pdf_path, json_path = sys.argv[1], sys.argv[2]
    json_path = Path(json_path)

    existing = []
    if json_path.exists():
        existing = json.loads(json_path.read_text())
    existing_dates = {r["date"] for r in existing}

    new_rows = find_wst_rows(pdf_path)
    added = 0
    for r in new_rows:
        if r["date"] not in existing_dates:
            existing.append(r)
            existing_dates.add(r["date"])
            added += 1

    # keep chronological order
    from datetime import datetime
    existing.sort(key=lambda r: datetime.strptime(r["date"], "%b %d, %Y"))

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(existing, indent=2))
    print(f"Parsed {len(new_rows)} rows from PDF, added {added} new date(s).")
    print(f"Total rows in {json_path}: {len(existing)}")


if __name__ == "__main__":
    main()
