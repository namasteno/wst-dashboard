# WST Dashboard — Automated Setup

## What this does
Every weekday, this repo automatically:
1. Receives the day's WGU Marketing Daily Report PDF (via Zapier → GitHub)
2. Parses WST's Inquiries/Intenders/App Complete out of it
3. Refits the Day-of-Week baseline and all three regression models (3/6/12-month)
4. Regenerates projections and backtest stats
5. Publishes the updated numbers to a live GitHub Pages dashboard

No manual screenshotting, no chat uploads — the page just stays current.

## One-time setup

### 1. Create the repo
Create a new **public** GitHub repo (GitHub Pages' free tier requires public,
unless you have GitHub Pro/Team for private Pages). Name it whatever you like
— `wst-dashboard` is fine. Commit all the files in this folder to it.

### 2. Turn on GitHub Pages
Repo → **Settings → Pages** → under "Build and deployment," set:
- Source: **Deploy from a branch**
- Branch: **main**, folder: **/docs**
- Save

Your dashboard will be live at `https://<your-username>.github.io/wst-dashboard/`
within a minute or two.

### 3. Connect Zapier (email → repo)
This is the piece that replaces your manual screenshot step.

- New Zap, trigger: **Email by Zapier** (or your Outlook/Gmail connector if
  you have the account type for it) — filter for sender
  `IR_TableauAdmin@wgu.edu` with an attachment.
- Action: **GitHub → Create or Update File**
  - Repo: your `wst-dashboard` repo
  - File path: `incoming/report.pdf`
  - File content: the email's PDF attachment
  - Commit message: anything, e.g. "Daily report {{date}}"

Every time that email lands, Zapier overwrites `incoming/report.pdf` with
today's PDF and commits it — and that commit is exactly what triggers the
GitHub Action below.

### 4. That's it
The Action (`.github/workflows/update-dashboard.yml`) is already wired to
fire on that commit. It also runs on a weekday-morning schedule as a
safety net in case Zapier is late, and you can always trigger it by hand
from the repo's **Actions** tab ("Run workflow").

## Before you trust it: test the PDF parser

The parser in `scripts/parse_report.py` looks for lines matching the
"Non - Funnel Daily Report" table format we've been working from all
along. **Real PDFs sometimes format tables differently than extracted
plain text suggests** — test it against one actual saved report before
relying on it:

```bash
pip install pdfplumber
python scripts/parse_report.py path/to/a/real/report.pdf docs/data/daily.json
cat docs/data/daily.json   # check the new row looks right
```

If it doesn't find the WST row, the most common fix is adjusting the
regex in `find_wst_rows()` to match your PDF's actual text layout —
send me a copy of the extracted text (`page.extract_text()`) and I can
tune it.

## Files

- `scripts/parse_report.py` — PDF → `docs/data/daily.json`
- `scripts/update_models.py` — `daily.json` → `docs/data/model_output.json`
  (weekday baselines, 3 regression fits, projections, backtest)
- `docs/index.html` — the live dashboard (plain HTML/JS, no build step)
- `.github/workflows/update-dashboard.yml` — the automation
- `docs/data/` — generated data, committed automatically (don't hand-edit)

## Adjusting holidays

`update_models.py` has a `HOLIDAYS` set near the top. Add future dates
there as you know them (Thanksgiving, Christmas, etc. for years beyond
what's listed) so the regression models keep discounting them correctly.
