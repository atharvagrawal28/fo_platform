# 📈 F&O Earnings Intelligence Platform

A production-grade earnings calendar for equity research analysts.

**Architecture:**
```
NSE/BSE APIs → GitHub Actions (pipeline) → Neon PostgreSQL → Streamlit Dashboard
```

Streamlit is **presentation-only** — no scraping, no heavy compute during user sessions.

---

## Project Structure

```
fo_platform/
├── pipeline/
│   ├── fetch.py       ← NSE→BSE→HTML waterfall fetch
│   ├── validate.py    ← Explicit validation rules
│   ├── enrich.py      ← F&O tag, sector, importance score
│   ├── store.py       ← PostgreSQL upserts + analytics cache
│   ├── seed.py        ← CSV reference data upserts
│   └── run.py         ← Orchestrator (entry point)
├── database/
│   ├── bootstrap.py   ← Idempotent schema + seed bootstrap
│   ├── connection.py  ← DB connection utility
│   ├── queries.py     ← All dashboard SELECT queries
│   └── migrations/
│       └── 001_initial_schema.sql
├── ui/
│   ├── app.py         ← Streamlit dashboard (reads DB only)
│   └── components/
│       ├── kpis.py
│       ├── charts.py
│       └── tables.py
├── data/              ← Static CSV reference files
├── configs/
│   └── settings.py    ← All config in one place
└── .github/workflows/
    ├── pipeline.yml   ← Scheduled ingestion
    └── keep_active.yml ← Monthly activity commit
```

---

## Step-by-Step Setup

### PART 1 — Neon PostgreSQL (5 minutes)

1. Go to **https://neon.tech** → Sign up free (GitHub login works)
2. Click **"New Project"** → name it `fo-platform`
3. Select region: **AWS ap-south-1 (Mumbai)** — closest to India
4. Click **Create Project**
5. On the project page, click **"Connection Details"**
6. Copy the **Connection string** — looks like:
   ```
   postgresql://username:password@ep-xxx.ap-south-1.aws.neon.tech/neondb?sslmode=require
   ```
   **Save this. You will use it in every step below.**

---

### PART 2 — Local Setup

#### Step 1: Extract and enter the project
```bash
cd fo_platform
```

#### Step 2: Create virtual environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

#### Step 3: Install dependencies
```bash
pip install -r requirements.txt
```

#### Step 4: Set up your .env file
```bash
# Copy the template
cp .env.example .env
```
Open `.env` in VS Code and paste your Neon connection string:
```
DATABASE_URL=postgresql://user:pass@ep-xxx.ap-south-1.aws.neon.tech/neondb?sslmode=require
```

#### Step 5: Optional local smoke test

For production, you can skip local migration and local seeding.
The GitHub Actions pipeline now runs `database/bootstrap.py` automatically
inside `python pipeline/run.py`, so a fresh Neon database is prepared from the
cloud job before live data is ingested.

If you still want to test locally:
```bash
python pipeline/run.py
```

**Expected output:**
```
INFO | Bootstrapping database schema and reference data...
INFO | Pipeline starting | run_id=run_20250514_083022_abc123
INFO | Step 1/4: Fetching data...
INFO | ✅ fetch success | source=nse rows=45
INFO | Step 2/4: Validating...
INFO | Validation passed | clean_rows=42
INFO | Step 3/4: Enriching...
INFO | Enrichment complete | fo=28 nifty50=12 sector_mapped=38
INFO | Step 4/4: Storing to PostgreSQL...
INFO | Store done | upserted=42
INFO | Pipeline SUCCESS | duration=8.3s rows_stored=42 source=nse
```

If a local run is blocked by NSE/BSE, ignore the local result and use GitHub
Actions as the production path. The production pipeline does not depend on your
residential IP.

#### Step 6: Run the dashboard locally
```bash
streamlit run ui/app.py
```
Opens at `http://localhost:8501`

---

### PART 3 — GitHub Setup

#### Step 9: Create GitHub repository
1. Go to **https://github.com** → click **+** → **New repository**
2. Name: `fo-earnings-platform`
3. Set to **Public** (required for Streamlit Community Cloud free tier)
4. Do NOT add README/gitignore (you already have them)
5. Click **Create repository**

#### Step 10: Push code to GitHub
```bash
git init
git add .
git commit -m "Initial: F&O Earnings Intelligence Platform"
git remote add origin https://github.com/YOUR_USERNAME/fo-earnings-platform.git
git branch -M main
git push -u origin main
```

#### Step 11: Add DATABASE_URL as GitHub Secret
1. On your GitHub repo page → **Settings** tab
2. Left sidebar → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `DATABASE_URL`
5. Value: paste your full Neon connection string
6. Click **Add secret**

GitHub Actions will now use this secret when running the pipeline.

#### Step 12: Trigger the first GitHub Actions run
1. Go to your repo → **Actions** tab
2. Click **"Earnings Pipeline"** workflow
3. Click **"Run workflow"** → **Run workflow** (green button)
4. Watch the logs — should complete in 60–120 seconds

After this, it runs automatically every weekday at 8:00 AM IST and 4:30 PM IST,
plus once on weekends at 8:00 AM IST.

---

### PART 4 — Streamlit Cloud Deployment

#### Step 13: Deploy to Streamlit Community Cloud
1. Go to **https://share.streamlit.io** → sign in with GitHub
2. Click **"New app"**
3. Fill in:
   - Repository: `YOUR_USERNAME/fo-earnings-platform`
   - Branch: `main`
   - Main file path: `ui/app.py`
4. Click **"Advanced settings"** → paste your secrets (see Step 14)
5. Click **Deploy**

#### Step 14: Add secrets to Streamlit Cloud
In the "Advanced settings" before deploying (or App Settings → Secrets after):

```toml
DATABASE_URL = "postgresql://user:pass@ep-xxx.ap-south-1.aws.neon.tech/neondb?sslmode=require"
```

The dashboard will now read live data from Neon that GitHub Actions keeps fresh.

---

### PART 5 — Verification Checklist

After full setup, verify each layer:

| Check | Command / URL | Expected |
|-------|---------------|----------|
| DB bootstrap ran | Actions log | migration + seed logs before ingestion |
| Reference data seeded | `SELECT COUNT(*) FROM fo_universe` | ~187 rows |
| Pipeline runs in GitHub | Actions tab → Earnings Pipeline | Green checkmark |
| Dashboard loads locally | `streamlit run ui/app.py` | Opens at :8501 |
| Streamlit Cloud live | your-app.streamlit.app | Dashboard with data |

---

## Daily Usage (Once Deployed)

**You do nothing.** GitHub Actions runs the pipeline automatically:
- 8:00 AM IST every weekday
- 4:30 PM IST every weekday
- 8:00 AM IST once on weekends

The Streamlit dashboard reads Neon on each load. Use the sidebar refresh button
if you already have the tab open and want to reload the latest database state.

**To manually trigger a refresh:**
- GitHub Actions tab → Run workflow, OR
- Click 🔄 Refresh in the dashboard sidebar (reconnects to DB)

**To update the F&O universe list:**
1. Edit `data/fo_universe.csv`
2. Commit and push
3. Run the `Earnings Pipeline` workflow manually, or wait for the next schedule

The pipeline bootstraps and seeds reference data before every ingestion, so the
CSV change reaches Neon from GitHub without a local `seed.py` run.

**Keep scheduled workflows active:**
`.github/workflows/keep_active.yml` creates one empty commit on the 1st of each
month. This is intentionally separate from ingestion so GitHub continues seeing
repository activity even when you have not pushed code recently.

**Keep Streamlit awake:**
If you are using Streamlit Community Cloud and want to avoid cold starts, create
a free UptimeRobot HTTPS monitor for your Streamlit app URL and ping it every
6 hours. This does not touch Neon data; it only keeps the public dashboard warm.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `DATABASE_URL is not set` | Add it to `.env` (local) or Streamlit Secrets (cloud) |
| `Connection refused` | Check Neon dashboard — project must be active |
| Pipeline shows "NSE failed" | Normal — BSE fallback activates automatically |
| Dashboard shows "no data" | Confirm the GitHub `DATABASE_URL` secret, then manually run `Earnings Pipeline` once |
| Stale dashboard after idle time | Use the sidebar refresh button; the app also auto-reconnects before each DB query |
| GitHub Actions job red | Check Actions logs; usually NSE timeout — next run auto-retries |
| Streamlit Cloud error | Check App logs; usually missing `DATABASE_URL` in secrets |

---

## Updating Schema Later

Never edit `001_initial_schema.sql` after deployment.
Create new migration files instead:

```bash
# Example: add a new column
# Create: database/migrations/002_add_exchange_column.sql
ALTER TABLE earnings_calendar ADD COLUMN IF NOT EXISTS exchange TEXT DEFAULT 'NSE';

# Run against Neon:
psql $DATABASE_URL -f database/migrations/002_add_exchange_column.sql
```

---

*Not financial advice. For research purposes only.*
