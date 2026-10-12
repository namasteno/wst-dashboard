"""
Reads data/daily.json (actuals) and produces data/model_output.json
containing: weekday baselines, regression coefficients for three
lookback windows, daily projections through the end of next month,
and a rolling backtest (each model's error on the last N actual days).

Usage:
    python update_models.py data/daily.json data/model_output.json
"""
import sys
import json
import numpy as np
from datetime import datetime, date, timedelta
from pathlib import Path

# Official day-by-day adaptive budget (App Complete), provided by WGU for
# Oct-Dec 2026. Keyed by "Mon D, YYYY" to match the date format used
# throughout this pipeline. Add more months here as WGU provides them.
_TARGETS_PATH = Path(__file__).parent / "daily_targets.json"
DAILY_TARGETS = json.loads(_TARGETS_PATH.read_text()) if _TARGETS_PATH.exists() else {}

IDX = {"Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6, "Sun": 7}

# Add/adjust known holidays here as the calendar rolls forward
HOLIDAYS = {
    date(2025, 11, 27), date(2025, 12, 25), date(2026, 1, 1),
    date(2026, 5, 25), date(2026, 7, 4), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25), date(2027, 1, 1),
}


def load_actuals(path):
    rows = json.loads(Path(path).read_text())
    out = []
    for r in rows:
        dt = datetime.strptime(r["date"], "%b %d, %Y").date()
        out.append((dt, r["Inquiries"], r["Intenders"], r["App Complete"]))
    out.sort(key=lambda x: x[0])
    return out


def weekday_baselines(records, lookback_start):
    sums, counts = {}, {}
    for dt, _, _, app in records:
        if dt < lookback_start:
            continue
        wd = dt.strftime("%a")
        sums[wd] = sums.get(wd, 0) + app
        counts[wd] = counts.get(wd, 0) + 1
    return {wd: round(sums[wd] / counts[wd]) for wd in sums}


def fit_regression(records, start_d, end_d):
    window = [(dt, app) for dt, _, _, app in records if start_d <= dt <= end_d]
    if len(window) < 14:
        return None  # not enough data yet
    t0 = window[0][0]
    X_rows, y = [], []
    for dt, app in window:
        t = (dt - t0).days + 1
        wd = dt.strftime("%a")
        row = [1.0, t] + [1.0 if wd == d else 0.0 for d in
                          ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
        row.append(1.0 if dt in HOLIDAYS else 0.0)
        X_rows.append(row)
        y.append(app)
    X, y = np.array(X_rows), np.array(y)
    coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_pred = X @ coefs
    r2 = 1 - np.sum((y - y_pred) ** 2) / np.sum((y - y.mean()) ** 2)
    return {"coefs": coefs.tolist(), "t0": t0.isoformat(), "r2": round(r2, 4), "n": len(window)}


def predict_regression(model, dt):
    coefs = model["coefs"]
    t0 = date.fromisoformat(model["t0"])
    t = (dt - t0).days + 1
    wd = dt.strftime("%a")
    val = coefs[0] + coefs[1] * t
    if wd in IDX:
        val += coefs[IDX[wd]]
    if dt in HOLIDAYS:
        val += coefs[8]
    return max(round(val), 0)


def predict_dow(baselines, dt):
    return baselines.get(dt.strftime("%a"), 0)


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main():
    if len(sys.argv) != 3:
        print("Usage: update_models.py <daily_json> <output_json>")
        sys.exit(1)

    daily_path, out_path = sys.argv[1], sys.argv[2]
    records = load_actuals(daily_path)
    if not records:
        print("No actuals found — nothing to model yet.")
        sys.exit(0)

    last_actual = records[-1][0]
    today = last_actual  # treat the latest actual day as "today" for projection purposes

    # --- Day-of-Week baseline: last 90 days ---
    dow_baselines = weekday_baselines(records, today - timedelta(days=90))

    # --- Three regression windows, all ending on the latest actual day ---
    windows = {
        "3mo": today - timedelta(days=90),
        "6mo": today - timedelta(days=182),
        "12mo": today - timedelta(days=365),
    }
    models = {}
    for key, start_d in windows.items():
        fit = fit_regression(records, start_d, today)
        if fit:
            models[key] = fit

    # --- Project forward through the end of NEXT month ---
    if today.month == 12:
        proj_end = date(today.year + 1, 2, 1) - timedelta(days=1)
    else:
        next_month = today.month + 2
        year = today.year + (1 if next_month > 12 else 0)
        next_month = ((next_month - 1) % 12) + 1
        proj_end = date(year, next_month, 1) - timedelta(days=1)

    projections = []
    for dt in daterange(today + timedelta(days=1), proj_end):
        row = {"date": dt.strftime("%b %-d, %Y"), "Proj: Day-of-Week": predict_dow(dow_baselines, dt)}
        for key, model in models.items():
            row[f"Proj: Regr-{key}"] = predict_regression(model, dt)
        projections.append(row)

    # --- Backtest: how each model would have called the last 14 actual days ---
    backtest_days = records[-14:]
    backtest = {"Proj: Day-of-Week": {"label": "Day-of-Week", "totalError": 0, "days": len(backtest_days)}}
    for key, model in models.items():
        backtest[f"Proj: Regr-{key}"] = {"label": f"Regression ({key})", "totalError": 0, "days": len(backtest_days)}

    for dt, _, _, app in backtest_days:
        backtest["Proj: Day-of-Week"]["totalError"] += abs(app - predict_dow(dow_baselines, dt))
        for key, model in models.items():
            pred = predict_regression(model, dt)
            backtest[f"Proj: Regr-{key}"]["totalError"] += abs(app - pred)

    output = {
        "generated": datetime.now(tz=__import__("datetime").timezone.utc).isoformat(),
        "last_actual_date": last_actual.strftime("%b %-d, %Y"),
        "dow_baselines": dow_baselines,
        "regression_models": {k: {"r2": v["r2"], "n": v["n"], "coefs": v["coefs"]} for k, v in models.items()},
        "projections": projections,
        "backtest": backtest,
        # Official daily targets, independent of actual/projection status —
        # plottable for ANY date in range, including past actual days.
        "daily_targets": DAILY_TARGETS,
    }

    Path(out_path).write_text(json.dumps(output, indent=2))
    print(f"Wrote {out_path}")
    print(f"Backtest (last {len(backtest_days)} days):")
    for key, b in sorted(backtest.items(), key=lambda kv: kv[1]["totalError"]):
        print(f"  {b['label']}: {b['totalError']}")


if __name__ == "__main__":
    main()
