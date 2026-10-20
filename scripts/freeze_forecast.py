#!/usr/bin/env python3
"""
freeze_forecast.py  --  lock each month's forecast so it stops moving.

Run AFTER scripts/update_models.py. It:
  1. Builds a "frozen" forecast for the current month (and the next month once
     the current one is complete) using ONLY data through the previous
     month-end, so there is no look-ahead. The frozen forecast is saved to
     docs/data/frozen_forecast.json and never overwritten.
  2. Rewrites docs/data/model_output.json so that every date in a frozen month
     carries the frozen Proj values -- including days that already have actuals,
     so the dashboard can plot Actual vs Model vs Target for the whole month.
  3. Keeps the day's live refit under "live_projections" for reference.

The 14-day backtest and dow_baselines in model_output.json are untouched: they
are model-quality checks and should keep using the latest data.

Usage:
  python scripts/freeze_forecast.py                    # normal daily run
  python scripts/freeze_forecast.py --refreeze 2026-10 # deliberately re-lock a month
  python scripts/freeze_forecast.py --backfill-from 2026-04
      # one-time: rebuild frozen forecasts for every earlier month from Apr 2026 on, each
      # using only the data that existed before that month began. Lets the dashboard's
      # month filter score the models on past months. Months already frozen are left alone.
"""
import argparse
import calendar
import datetime as dt
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
DAILY = DATA / "daily.json"
MODEL = DATA / "model_output.json"
FROZEN = DATA / "frozen_forecast.json"

# Same windows update_models.py uses (calendar days back from last actual date).
LOOKBACKS = {"3mo": 90, "6mo": 182, "12mo": 365}
DOW_DAYS = 90
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse(s):
    return dt.datetime.strptime(s, "%b %d, %Y").date()


def fmt(d):
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def month_key(d):
    return f"{d.year}-{d.month:02d}"


def nth_weekday(y, m, wd, n):
    days = [dt.date(y, m, x) for x in range(1, calendar.monthrange(y, m)[1] + 1)
            if dt.date(y, m, x).weekday() == wd]
    return days[n - 1] if n > 0 else days[-1]


def holidays(y):
    return {nth_weekday(y, 5, 0, -1), dt.date(y, 7, 4), nth_weekday(y, 9, 0, 1),
            nth_weekday(y, 11, 3, 4), dt.date(y, 12, 25), dt.date(y, 1, 1)}


HOLIDAYS = set().union(*[holidays(y) for y in range(2024, 2031)])


def features(day, t0):
    # intercept, trend (t starts at 1), Tue..Sun dummies (Mon = baseline), holiday
    return [1, (day - t0).days + 1] + [1.0 if day.weekday() == k else 0.0 for k in range(1, 7)] \
        + [1.0 if day in HOLIDAYS else 0.0]


def fit(actuals, last, lookback):
    t0 = last - dt.timedelta(lookback)
    days = [d for d in sorted(actuals) if t0 <= d <= last]
    X = np.array([features(d, t0) for d in days], float)
    y = np.array([actuals[d] for d in days], float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    r2 = 1 - ((y - X @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return b, float(r2), len(days), t0


def dow_baselines(actuals, last):
    days = sorted(d for d in actuals if d <= last)[-DOW_DAYS:]
    out = {}
    for i, name in enumerate(WEEKDAYS):
        v = [actuals[d] for d in days if d.weekday() == i]
        out[name] = round(sum(v) / len(v))
    return out


def build_month(actuals, vintage, first, last_day):
    fits = {k: fit(actuals, vintage, lb) for k, lb in LOOKBACKS.items()}
    base = dow_baselines(actuals, vintage)
    rows, d = [], first
    while d <= last_day:
        row = {"date": fmt(d), "Proj: Day-of-Week": base[WEEKDAYS[d.weekday()]]}
        for k, (b, _, _, t0) in fits.items():
            row[f"Proj: Regr-{k}"] = int(round(float(np.dot(features(d, t0), b))))
        rows.append(row)
        d += dt.timedelta(1)
    return {
        "vintage": fmt(vintage),
        "frozen_on": dt.date.today().isoformat(),
        "models": {k: {"r2": round(r2, 4), "n": n, "t0": t0.isoformat(),
                       "trend_per_day": round(float(b[1]), 4)}
                   for k, (b, r2, n, t0) in fits.items()},
        "projections": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refreeze", metavar="YYYY-MM", help="discard and rebuild this month's freeze")
    ap.add_argument("--backfill-from", metavar="YYYY-MM",
                    help="freeze every not-yet-frozen month from here up to the current one")
    args = ap.parse_args()

    actuals = {parse(r["date"]): r["App Complete"] for r in json.loads(DAILY.read_text())}
    model = json.loads(MODEL.read_text())
    last = max(actuals)
    frozen = json.loads(FROZEN.read_text()) if FROZEN.exists() else {"months": {}}

    def freeze(key, backfilled=False):
        y, m = map(int, key.split("-"))
        first = dt.date(y, m, 1)
        prior = [d for d in actuals if d < first]
        if not prior:
            return
        vintage = max(prior)  # last available day before the month starts
        info = build_month(actuals, vintage, first, dt.date(y, m, calendar.monthrange(y, m)[1]))
        if backfilled:
            info["backfilled"] = True
        frozen["months"][key] = info
        print(f"Froze {key} using data through {fmt(vintage)}" + (" (backfill)" if backfilled else ""))

    candidates = {month_key(last), month_key(last + dt.timedelta(1))}
    if args.refreeze:
        candidates.add(args.refreeze)
        frozen["months"].pop(args.refreeze, None)
    for key in sorted(candidates):
        if key not in frozen["months"]:
            freeze(key)

    if args.backfill_from:
        y, m = map(int, args.backfill_from.split("-"))
        while f"{y}-{m:02d}" < month_key(last):
            key = f"{y}-{m:02d}"
            if key not in frozen["months"]:
                freeze(key, backfilled=True)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    FROZEN.write_text(json.dumps(frozen, indent=2))

    # Merge frozen values over the live projections (idempotent across re-runs).
    live = model.get("live_projections", model["projections"])
    merged = {p["date"]: dict(p) for p in live}
    for info in frozen["months"].values():
        for p in info["projections"]:
            merged[p["date"]] = {**merged.get(p["date"], {}), **p}
    model["live_projections"] = live
    model["projections"] = [merged[k] for k in sorted(merged, key=parse)]
    model["frozen"] = {k: {"vintage": v["vintage"], "models": v["models"]}
                       for k, v in frozen["months"].items()}
    MODEL.write_text(json.dumps(model, indent=2))
    print(f"model_output.json updated; frozen months: {', '.join(sorted(frozen['months']))}")


if __name__ == "__main__":
    main()
