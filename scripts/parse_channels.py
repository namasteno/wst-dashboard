#!/usr/bin/env python3
"""
Turns the Tableau channel export(s) into docs/data/channel_data.json.

Export from the Tableau EXPORT view with School = WST, 1st Display = Channel, both metrics
(Net Applicants + Degree Intenders), then Period = Monthly and/or Weekly and a wide date range.
Drop the downloaded file(s) in incoming/ named channels*.csv (any extra name part is fine, e.g.
incoming/channels_monthly.csv, incoming/channels_weekly.csv). Each file's Period column says
whether its rows are weekly or monthly, so the same script handles both.

Usage:
    python scripts/parse_channels.py incoming/channels*.csv [--out docs/data/channel_data.json]
                                                            [--updated YYYY-MM-DD]

Each run replaces the weeks/months that appear in the file(s) and keeps all others, so
re-exporting the full range every week quietly picks up WGU's late revisions. The "updated"
date only moves when the numbers change, so the workflow re-reading an old file every day
does not make stale data look fresh.

Output shape:
{
  "updated": {"monthly": "2026-10-22", "weekly": null},
  "monthly": {"2026-10": {"Direct": {"intenders": 916, "converted": 906,
                                      "prior_intenders": 2084, "prior_converted": 1976}, ...}},
  "weekly":  {"2026-10-25": {...same...}}       # keyed by the week-ending date
}
prior_* are the same period one year earlier, as supplied by Tableau.
"""
import argparse
import csv
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

DATE_FORMATS = ["%d %b %y", "%d-%b-%y", "%d %b %Y", "%d-%b-%Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"]

# Tableau name -> the short names the dashboard uses
CHANNEL_ALIASES = {
    "paid search (trademark)": "PS-TM",
    "paid search (non-trademark)": "PS-NTM",
    "paid search (non trademark)": "PS-NTM",
    "paid search": "Paid Search (other)",
}


def read_text(path):
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig")
    for enc in ("utf-8", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: could not work out the file encoding")


def parse_date(text):
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unrecognised date {text!r}")


def clean_channel(name):
    name = re.sub(r"\s+", " ", name.strip())
    name = re.sub(r"\(\s+", "(", name)
    name = re.sub(r"\s+\)", ")", name)
    return CHANNEL_ALIASES.get(name.lower(), name)


def to_int(text):
    text = (text or "").replace(",", "").strip()
    if text in ("", "Null", "null", "-"):
        return None
    return int(round(float(text)))


def read_rows(path):
    text = read_text(path)
    first = text.splitlines()[0] if text.strip() else ""
    delim = "\t" if "\t" in first else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]
    needed = {"end date", "1st display", "metric", "volume", "period"}
    missing = needed - set(rows[0]) if rows else needed
    if missing:
        raise ValueError(f"{path}: missing column(s) {sorted(missing)}; found {sorted(rows[0]) if rows else []}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="docs/data/channel_data.json")
    ap.add_argument("--updated", default=date.today().isoformat())
    args = ap.parse_args()

    out_path = Path(args.out)
    data = json.loads(out_path.read_text()) if out_path.exists() else {}
    data.setdefault("updated", {"monthly": None, "weekly": None})
    data.setdefault("monthly", {})
    data.setdefault("weekly", {})

    skipped_metrics = {}
    blank_as_zero = 0
    changed = set()  # which of monthly/weekly actually got new or revised numbers
    for f in args.files:
        # period ("monthly"/"weekly") -> period key -> channel -> metric values
        found = {}
        for r in read_rows(f):
            period = r["period"].lower()
            if period not in ("monthly", "weekly"):
                skipped_metrics[f"period={r['period']}"] = skipped_metrics.get(f"period={r['period']}", 0) + 1
                continue
            metric = r["metric"].lower()
            if "intender" in metric:
                slot = "intenders"
            elif metric.startswith("net"):
                slot = "converted"
            else:
                skipped_metrics[r["metric"]] = skipped_metrics.get(r["metric"], 0) + 1
                continue
            end = parse_date(r["end date"])
            pkey = f"{end.year}-{end.month:02d}" if period == "monthly" else end.isoformat()
            volume = to_int(r["volume"])
            if volume is None:
                # Tableau leaves Volume blank (YoY Diff 0) for a channel with no activity that period
                if r.get("yoy diff", "") in ("", "0"):
                    volume = 0
                    blank_as_zero += 1
                else:
                    continue
            entry = found.setdefault(period, {}).setdefault(pkey, {}).setdefault(clean_channel(r["1st display"]), {})
            entry[slot] = volume
            prior = to_int(r.get("prior volume", ""))
            if prior is not None:
                entry["prior_" + slot] = prior

        for period, periods in found.items():
            for pkey, channels in periods.items():
                complete = {}
                for ch, v in channels.items():
                    if "intenders" in v and "converted" in v:
                        complete[ch] = {k: v[k] for k in ("intenders", "converted", "prior_intenders", "prior_converted") if k in v}
                    else:
                        print(f"WARNING: {period} {pkey} {ch}: only one of the two metrics was exported, skipped.")
                if data[period].get(pkey) != complete:
                    changed.add(period)
                data[period][pkey] = complete
            keys = sorted(periods)
            print(f"{Path(f).name}: {period}: {len(keys)} period(s), {keys[0]} to {keys[-1]}")

    # The stamp means "the numbers last changed": re-running on an unchanged file leaves it alone.
    for period in changed:
        data["updated"][period] = args.updated
    for period in ("monthly", "weekly"):
        if data[period] and not data["updated"].get(period):
            data["updated"][period] = args.updated
    if blank_as_zero:
        print(f"Treated {blank_as_zero} blank Volume cell(s) as 0 (channel had no activity that period).")
    if skipped_metrics:
        print("Ignored rows:", ", ".join(f"{k} x{n}" for k, n in skipped_metrics.items()))

    data["monthly"] = dict(sorted(data["monthly"].items()))
    data["weekly"] = dict(sorted(data["weekly"].items()))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=1))
    print(f"Wrote {out_path}: {len(data['monthly'])} month(s), {len(data['weekly'])} week(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # keep the workflow log readable
        print(f"ERROR: {e}")
        sys.exit(1)
