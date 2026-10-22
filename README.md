# WST Dashboard

Live dashboard for WGU School of Technology's enrollment funnel (Inquiries → Intenders → App Complete): pacing against the monthly goal, forecasts, Intender-to-App conversion, and conversion by channel.

Live at <https://namasteno.github.io/wst-dashboard/>. Add `?month=2026-09` to the address to open a specific month.

## Daily routine (about a minute)

1. Download the PDF attached to the day's **Marketing Daily Report** email (sender `IR_TableauAdmin@wgu.edu`).
2. Upload it to the repo's `incoming/` folder named exactly `report.pdf`, overwriting yesterday's file, and commit.
3. That commit starts the GitHub Action in `.github/workflows/update-dashboard.yml`, which runs these steps in order:
   1. **Parse report PDF** (`scripts/parse_report.py`): reads WST's Inquiries, Intenders and App Complete from the College table, adds new days, and applies WGU's later revisions to earlier days in the same month.
   2. **Parse channel exports** (`scripts/parse_channels.py`): only if `incoming/channels*.csv` exists (see below).
   3. **Refit models** (`scripts/update_models.py`): weekday baseline plus 3, 6 and 12-month regressions, projections through the end of next month, and the rolling 14-day backtest.
   4. **Freeze monthly forecast** (`scripts/freeze_forecast.py`): locks each month's forecast at the prior month-end so Actual vs. Model vs. Target stays consistent all month.
   5. **Commit** everything in `docs/data/`.
4. The dashboard updates within a minute or two. You can also run the Action by hand from the **Actions** tab ("Run workflow").

## Channel data (weekly)

Channel numbers come from the Tableau **EXPORT** view, not the daily PDF.

1. In the view set School = WST, 1st Display = **Channel**, both metrics (**Net Applicants** and **Degree Intenders**), a wide date range, and Period = **Weekly** (or **Monthly**).
2. Download the data as a CSV and upload it to `incoming/` as `channels_weekly.csv` (or `channels_monthly.csv`). Re-export the full date range each time so WGU's late revisions replace the older numbers.
3. The commit starts the Action, which writes `docs/data/channel_data.json`. The channel section's "updated" date moves only when the numbers actually change.

Use the downloaded CSV rather than reading numbers off the on-screen table: the on-screen table lists the smaller number first, which can swap the Net and Intenders labels.

## What's on the dashboard

A month selector at the top (tabs for Jul to Mar, plus an "Earlier" menu) filters every section:

- **Monthly pacing:** actual, projected total, goal and pace. Months without a goal show daily average and change vs. the prior month and last year.
- **Model confidence and error:** each model scored against the forecast frozen at the prior month-end, so it is a fair out-of-sample test. Available from April 2026.
- **Intender → App conversion:** month rate vs. prior month and last year, a weekly line with a 13-week average, and a day-by-day heatmap.
- **Trend:** Actual vs. Model vs. Target for the selected month (other ranges are in the Range menu).
- **Channel performance:** conversion by channel for the month, changes vs. prior month and last year, a "what moved conversion" breakdown (channel mix vs. rates inside channels), and a monthly or weekly grid.

## One-time setup (already done)

1. Create a **public** GitHub repo (free GitHub Pages requires public) and commit these files.
2. Repo → **Settings → Pages**: Source = Deploy from a branch, Branch = `main`, folder = `/docs`, Save.

## Files

| Path | What it is |
|---|---|
| `incoming/report.pdf` | Today's Marketing Daily Report (you upload this daily) |
| `incoming/channels_weekly.csv`, `channels_monthly.csv` | Tableau channel exports (you upload these) |
| `scripts/parse_report.py` | PDF → `docs/data/daily.json` |
| `scripts/parse_channels.py` | Channel CSVs → `docs/data/channel_data.json` |
| `scripts/update_models.py` | `daily.json` → `docs/data/model_output.json` |
| `scripts/freeze_forecast.py` | Locks each month's forecast → `docs/data/frozen_forecast.json` |
| `scripts/daily_targets.json` | Day-by-day budget (official for Oct to Dec 2026; estimated after that) |
| `docs/index.html` | The dashboard (plain HTML and JS, no build step) |
| `docs/data/` | Generated data, committed automatically. Don't hand-edit. |
| `docs/data/channel_actuals.json` | Old hand-entered channel snapshot. Only used for a month the channel export doesn't cover. |
| `.github/workflows/update-dashboard.yml` | The automation |

## Routine maintenance

- **New month's goal:** add it to `monthGoals` near the top of `docs/index.html`, and add the day-by-day budget to `scripts/daily_targets.json`.
- **Holidays:** add future dates to the `HOLIDAYS` set in `scripts/update_models.py` and to `HOLIDAY_DATES` in `docs/index.html`. (`freeze_forecast.py` works out holidays by rule through 2030.)
- **Past-month forecasts:** to rebuild frozen forecasts from an earlier month, run `python scripts/freeze_forecast.py --backfill-from 2026-04`. To re-lock one month: `--refreeze 2026-10`.

## Things to know

- **Revisions:** WGU revises recent days upward, usually by 1 to 2%. Each PDF only lists the current month, so earlier months in `daily.json` keep their first-reported values.
- **Missing days:** a few days are absent from the source reports (for example Jul 31 and Aug 31, 2026) and appear as gaps.
- **Recommended model:** the "recommended model" comes from the rolling 14-day backtest, which scores models on days they were already fit to, so shorter windows look better than they forecast. The frozen-forecast scoring is the fair comparison.
- **Unfinished weeks:** the newest week in the channel grid is marked with an asterisk. Its Intenders are still coming in, so its rates run high.

## Troubleshooting

- **Dashboard shows old numbers:** check the Actions tab for a failed run, then refresh the page.
- **Parser didn't pick up WST:** run `python scripts/parse_report.py incoming/report.pdf docs/data/daily.json` locally and check the output. If the PDF layout changed, adjust `find_wst_rows()` in `scripts/parse_report.py`.
- **A "revision" is skipped with a warning:** `parse_report.py` ignores changes over 10% on one day, treating them as a parse error. Check the PDF layout.
- **Channel export not read:** the file must be named `channels*.csv` and include the columns End Date, 1st Display, Metric, Volume and Period.
