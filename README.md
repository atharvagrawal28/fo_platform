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
│   ├── seed.py        ← One-time CSV → DB loader (run once)
│   └── run.py         ← Orchestrator (entry point)
├── database/
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
    └── pipeline.yml   ← Scheduled ingestion
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

#### Step 5: Create database schema (run once)
```bash
psql $DATABASE_URL -f database/migrations/001_initial_schema.sql
```

**If `psql` is not installed:**

Option A — Install it:
- Windows: Download PostgreSQL installer from postgresql.org (includes psql)
- Mac: `brew install postgresql`
- Ubuntu: `sudo apt install postgresql-client`

Option B — Use Neon's built-in SQL editor:
1. Go to your Neon project dashboard
2. Click **"SQL Editor"**
3. Paste the entire contents of `database/migrations/001_initial_schema.sql`
4. Click **Run**

#### Step 6: Seed reference data (run once)
```bash
python pipeline/seed.py
```
This loads fo_universe.csv, sector_map.csv, and index membership files
into PostgreSQL. Takes ~5 seconds.

**Expected output:**
```
INFO | fo_universe: loaded 187 rows
INFO | sector_map: loaded 187 rows
INFO | ✅ Seed complete.
```

#### Step 7: Run the pipeline (test it works)
```bash
python pipeline/run.py
```

**Expected output:**
```
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

If NSE is blocked (common from cloud IPs), you'll see BSE fallback or sample data with a warning. That's expected behaviour — the pipeline is working correctly.

#### Step 8: Run the dashboard locally
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

After this, it runs automatically on the market-hours schedule.

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
| DB schema exists | Neon SQL Editor: `\dt` | 6 tables listed |
| Reference data seeded | `SELECT COUNT(*) FROM fo_universe` | ~187 rows |
| Pipeline runs locally | `python pipeline/run.py` | SUCCESS in logs |
| Dashboard loads locally | `streamlit run ui/app.py` | Opens at :8501 |
| GitHub Actions runs | Actions tab → pipeline job | Green checkmark |
| Streamlit Cloud live | your-app.streamlit.app | Dashboard with data |

---

## Daily Usage (Once Deployed)

**You do nothing.** GitHub Actions runs the pipeline automatically:
- Every 30 min during Indian market hours (8 AM – 6 PM IST)
- Every 4 hours off-hours
- Once daily on weekends

The Streamlit dashboard always shows the latest data from PostgreSQL.

**To manually trigger a refresh:**
- GitHub Actions tab → Run workflow, OR
- Click 🔄 Refresh in the dashboard sidebar (reconnects to DB)

**To update the F&O universe list:**
1. Edit `data/fo_universe.csv`
2. Run `python pipeline/seed.py` (safe to re-run, uses upserts)
3. Commit and push

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `DATABASE_URL is not set` | Add it to `.env` (local) or Streamlit Secrets (cloud) |
| `Connection refused` | Check Neon dashboard — project must be active |
| Pipeline shows "NSE failed" | Normal — BSE fallback activates automatically |
| Dashboard shows "no data" | Run `python pipeline/run.py` first |
| `psql: command not found` | Use Neon SQL Editor instead for schema migration |
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
