"""
Parses the WGU "Marketing Daily Report" PDF and extracts WST's
Non-Funnel Daily Report rows (Inquiries, Intenders, App Complete).

Usage:
    python parse_report.py incoming/report.pdf data/daily.json

Adds any new dates found in the PDF to data/daily.json AND applies WGU's
later revisions to dates already stored (the report restates earlier days
as late applications are attributed, usually upward by a few percent). The
newest PDF is always treated as the source of truth, so it is safe to
re-run on the same file.
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

FIELDS = ("Inquiries", "Intenders", "App Complete")
MAX_REVISION = 0.10  # October revisions topped out near 5%; anything past 10% is treated as a parse error

DATE_RE = re.compile(
    r"([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
)


def find_wst_rows(pdf_path):
    """
    Pull each date row's WST columns (7th/8th/9th number: WSB, LSH, WST, WSE
    each have 3 columns) from the 'Non - Funnel Daily Report - College' table.

    The Region table later in the PDF repeats the same dates with a different
    column layout, so it must never be read as WST. If no page is labelled
    'College' (older layouts), fall back to the first row seen per date.
    """
    college_rows, other_rows = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "Non - Funnel Daily Report" not in text and "Non-Funnel Daily Report" not in text:
                continue
            is_college = ("Funnel Daily Report - College" in text
                          or "Funnel Daily Report \u2013 College" in text)
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
                row = {
                    "date": f"{mon.title()} {int(day)}, {year}",
                    "Inquiries": wst_inq,
                    "Intenders": wst_int,
                    "App Complete": wst_app,
                }
                (college_rows if is_college else other_rows).append(row)

    chosen = college_rows if college_rows else other_rows
    seen, rows = set(), []
    for r in chosen:  # first occurrence per date wins
        if r["date"] not in seen:
            seen.add(r["date"])
            rows.append(r)
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
    by_date = {r["date"]: r for r in existing}

    new_rows = find_wst_rows(pdf_path)
    added = revised = 0
    app_delta = 0
    for r in new_rows:
        cur = by_date.get(r["date"])
        if cur is None:
            existing.append(r)
            by_date[r["date"]] = r
            added += 1
            continue
        if all(cur.get(k) == r[k] for k in FIELDS):
            continue
        # Real revisions are a few percent. A big swing means the PDF layout shifted
        # and a different column was read, so keep what we have and say so.
        old_app = cur.get("App Complete") or 0
        if old_app and abs(r["App Complete"] - old_app) / old_app > MAX_REVISION:
            print(f"WARNING: {r['date']} App Complete {old_app} -> {r['App Complete']} "
                  f"looks like a parse error, not a revision; keeping {old_app}.")
            continue
        app_delta += r["App Complete"] - old_app
        cur.update({k: r[k] for k in FIELDS})
        revised += 1

    # keep chronological order
    from datetime import datetime
    existing.sort(key=lambda r: datetime.strptime(r["date"], "%b %d, %Y"))

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(existing, indent=2))
    print(f"Parsed {len(new_rows)} rows from PDF, added {added} new date(s), "
          f"revised {revised} earlier date(s) (App Complete {app_delta:+d}).")
    print(f"Total rows in {json_path}: {len(existing)}")


if __name__ == "__main__":
    main()
