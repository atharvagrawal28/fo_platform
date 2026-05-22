"""
ui/app.py — F&O Earnings Intelligence Platform
================================================
Presentation-only Streamlit dashboard.

Data source: data/earnings_calendar.csv and data/pipeline_log.json
committed to GitHub by the scheduled GitHub Actions pipeline.

No database. No API keys. Zero cost. Runs forever.

Run locally: streamlit run ui/app.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from configs.settings import LOOKAHEAD_DAYS
from database.queries import (
    get_daily_distribution,
    get_kpis,
    get_last_pipeline_run,
    get_pipeline_health,
    get_sector_concentration,
    get_sector_options,
    get_top_earnings,
    get_upcoming_results,
)
from ui.components.charts import (
    chart_daily_bar,
    chart_fo_donut,
    chart_importance_scatter,
    chart_sector_bar,
)
from ui.components.kpis import render_kpi_row
from ui.components.tables import (
    render_pipeline_health,
    render_results_table,
    render_top_earnings,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="F&O Earnings Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── CSS ───────────────────────────────────────────────────────────────────────
def _css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif !important;
        background-color: #0D0F1C !important;
        color: #E8EAF0 !important;
    }
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding-top: 1rem !important; max-width: 1400px; }
    section[data-testid="stSidebar"] {
        background: #141727 !important;
        border-right: 1px solid #1E2340 !important;
    }
    .stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid #1E2340; gap: 4px; }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important; border: none !important;
        color: #8B8FA8 !important; font-size: 0.85rem !important;
        border-radius: 8px 8px 0 0 !important; padding: 8px 16px !important;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(0,212,255,0.08) !important;
        color: #00D4FF !important;
        border-bottom: 2px solid #00D4FF !important;
    }
    .stDownloadButton > button {
        background: transparent !important; border: 1px solid #00D4FF !important;
        color: #00D4FF !important; border-radius: 8px !important;
        font-size: 0.82rem !important;
    }
    .stDownloadButton > button:hover {
        background: #00D4FF !important; color: #000 !important;
    }
    .stButton > button {
        background: transparent !important; border: 1px solid #1E2340 !important;
        color: #8B8FA8 !important; border-radius: 8px !important;
    }
    .stButton > button:hover { border-color: #00D4FF !important; color: #00D4FF !important; }
    [data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
    .sec-head {
        font-size: 0.82rem; font-weight: 600; color: #8B8FA8;
        text-transform: uppercase; letter-spacing: 0.07em;
        padding-bottom: 8px; border-bottom: 1px solid #1E2340;
        margin: 20px 0 14px;
    }
    </style>
    """, unsafe_allow_html=True)


# ── Data loading (cached per Streamlit session) ───────────────────────────────
@st.cache_data(ttl=300)  # refresh cache every 5 minutes
def _load_all_data(days: int):
    """Load all dashboard data from CSV files. Cached for 5 minutes."""
    return {
        "all_results":   get_upcoming_results(days=days),
        "kpis":          get_kpis(days=days),
        "daily_dist":    get_daily_distribution(days=days),
        "sector_conc":   get_sector_concentration(days=days),
        "top_earnings":  get_top_earnings(days=days, limit=10),
        "pipeline_logs": get_pipeline_health(limit=10),
        "last_run":      get_last_pipeline_run(),
        "sector_opts":   get_sector_options(),
    }


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _sidebar(sector_opts: pd.DataFrame, last_run: dict) -> dict:
    with st.sidebar:
        st.markdown("## ⚙️ Filters")
        st.markdown("---")

        fo_only  = st.checkbox("F&O stocks only")
        n50_only = st.checkbox("Nifty 50 only")

        st.markdown("**Sector**")
        sector_options = ["All"]
        if not sector_opts.empty:
            sector_options += sorted(sector_opts["sector"].dropna().astype(str).unique())
        selected_sector = st.selectbox("Sector", sector_options, label_visibility="collapsed")

        st.markdown("**Date Range**")
        today    = datetime.today().date()
        max_date = today + timedelta(days=LOOKAHEAD_DAYS)
        c1, c2   = st.columns(2)
        with c1: start = st.date_input("From", value=today,    min_value=today, max_value=max_date)
        with c2: end   = st.date_input("To",   value=max_date, min_value=today, max_value=max_date)

        if end < start:
            end = start
            st.caption("End date set to match start date.")

        st.markdown("---")
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown(
            '<div style="font-size:0.68rem;color:#8B8FA8;text-align:center;margin-top:4px">'
            'Pipeline runs 8AM &amp; 4:30PM IST daily</div>',
            unsafe_allow_html=True,
        )

        # Pipeline status mini-panel
        if last_run:
            status  = last_run.get("status", "unknown")
            s_color = "#00C896" if status == "success" else "#FF6B6B"
            ts_raw  = last_run.get("started_at")
            ts = pd.to_datetime(ts_raw).strftime("%d %b %H:%M") if ts_raw else "—"
            st.markdown(
                f"""
                <div style="font-size:0.72rem;color:#8B8FA8;line-height:2;margin-top:8px">
                ⚙️ Pipeline: <b style="color:{s_color}">{status}</b><br>
                🕐 Last run: <b style="color:#E8EAF0">{ts}</b><br>
                📡 Source: <b style="color:#E8EAF0">{last_run.get('source_used','—')}</b>
                </div>
                """,
                unsafe_allow_html=True,
            )

    return dict(
        search="", fo_only=fo_only, n50_only=n50_only,
        sector=selected_sector, start=start, end=end,
    )


# ── Header ────────────────────────────────────────────────────────────────────
def _run_timestamp(last_run: dict) -> pd.Timestamp | None:
    if not last_run:
        return None
    raw = last_run.get("started_at")
    if not raw:
        return None
    ts = pd.to_datetime(raw, errors="coerce")
    return None if pd.isna(ts) else ts


def _run_age_hours(last_run: dict) -> float | None:
    ts = _run_timestamp(last_run)
    if ts is None:
        return None
    now = pd.Timestamp.now(tz=ts.tz) if ts.tzinfo else pd.Timestamp.now()
    return max(0.0, (now - ts).total_seconds() / 3600)


def _header(last_run: dict, db_rows: int = 0):
    ts = "—"
    run_ts = _run_timestamp(last_run)
    if run_ts is not None:
        ts = run_ts.strftime("%d %b %Y, %H:%M IST")
    source    = last_run.get("source_used", "—") if last_run else "—"
    age_hours = _run_age_hours(last_run)
    is_stale  = age_hours is not None and age_hours > 36
    freshness = "STALE DATA" if is_stale else "CURRENT DATA"
    freshness_color = "#FFB347" if is_stale else "#00C896"
    age_text  = "unknown age" if age_hours is None else f"{age_hours:.1f}h old"
    rows_text = f"{db_rows:,} companies tracked" if db_rows else "—"

    st.markdown(
        f"""
        <div style="padding:16px 0 20px;border-bottom:1px solid #1E2340;
                    margin-bottom:20px;display:flex;justify-content:space-between;
                    align-items:flex-end;flex-wrap:wrap;gap:8px">
            <div>
                <span style="font-size:1.8rem;font-weight:700;
                             letter-spacing:-.02em;color:#E8EAF0">
                    📈 F&amp;O Earnings Intelligence
                </span>
                <span style="display:inline-block;margin-left:10px;
                             background:rgba(0,200,150,.12);
                             border:1px solid rgba(0,200,150,.3);
                             color:#00C896;padding:2px 10px;
                             border-radius:20px;font-size:.7rem;
                             font-weight:600;letter-spacing:.08em">CSV + GitHub</span>
                <span style="display:inline-block;margin-left:6px;
                             background:rgba(255,179,71,.10);
                             border:1px solid {freshness_color};
                             color:{freshness_color};padding:2px 10px;
                             border-radius:20px;font-size:.7rem;
                             font-weight:600;letter-spacing:.08em">{freshness}</span>
            </div>
            <div style="font-size:0.75rem;color:#8B8FA8;
                        font-family:'IBM Plex Mono',monospace;text-align:right">
                Last update: {ts}<br>
                Source: {source} &nbsp;|&nbsp; {rows_text} &nbsp;|&nbsp; {age_text}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Filter application ────────────────────────────────────────────────────────
def _apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    if f.get("search", "").strip():
        term = f["search"].strip()
        mask = d["company_name"].str.contains(term, case=False, na=False)
        if "symbol" in d.columns:
            mask = mask | d["symbol"].str.contains(term, case=False, na=False)
        d = d[mask]
    if f.get("fo_only"):
        d = d[d["is_fo"].astype(bool)]
    if f.get("n50_only"):
        d = d[d["is_nifty50"].astype(bool)]
    if f.get("sector") and f["sector"] != "All":
        d = d[d["sector"] == f["sector"]]
    if f.get("start"):
        d = d[d["result_date"] >= pd.Timestamp(f["start"])]
    if f.get("end"):
        d = d[d["result_date"] <= pd.Timestamp(f["end"])]
    return d.reset_index(drop=True)


# ── Empty-data state ──────────────────────────────────────────────────────────
def _show_empty_data():
    st.warning(
        "**No earnings data yet.**\n\n"
        "The GitHub Actions pipeline hasn't run yet. Go to your GitHub repo → "
        "**Actions → Earnings Pipeline → Run workflow** to trigger the first run. "
        "After that, it runs automatically twice a day and commits updated CSV files.",
        icon="📭",
    )
    st.stop()


def _empty_kpis() -> dict:
    return {
        "total": 0, "fo_count": 0, "nifty50_count": 0, "banknifty_count": 0,
        "today_count": 0, "tomorrow_count": 0,
        "week_count": 0, "next_week_count": 0,
        "fo_week_count": 0, "nifty50_week_count": 0,
        "fo_pct": 0.0, "lookahead_days": LOOKAHEAD_DAYS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    _css()

    with st.spinner("Loading data…"):
        data = _load_all_data(days=LOOKAHEAD_DAYS)

    all_results   = data["all_results"]
    kpis          = data["kpis"]
    daily_dist    = data["daily_dist"]
    sector_conc   = data["sector_conc"]
    top_earnings  = data["top_earnings"]
    pipeline_logs = data["pipeline_logs"]
    last_run      = data["last_run"]
    sector_opts   = data["sector_opts"]

    db_rows = len(all_results) if not all_results.empty else 0

    # Sidebar (needs sector list + last run for the status panel)
    filters = _sidebar(sector_opts, last_run)

    # Header
    _header(last_run, db_rows=db_rows)

    # Empty state
    if all_results.empty and kpis["total"] == 0:
        _show_empty_data()

    # Apply sidebar filters
    filtered = _apply_filters(all_results, filters)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    t1, t2, t3, t4, t5 = st.tabs([
        "📊 Overview",
        "📋 All Results",
        "🎯 F&O Spotlight",
        "🏭 Sectors",
        "⚙️ Pipeline Health",
    ])

    # ── Tab 1: Overview ───────────────────────────────────────────────────────
    with t1:
        render_kpi_row(kpis)

        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown('<div class="sec-head">Daily Breakdown</div>', unsafe_allow_html=True)
            st.plotly_chart(
                chart_daily_bar(daily_dist),
                use_container_width=True,
                key="overview_daily_breakdown",
            )
        with c2:
            st.markdown('<div class="sec-head">F&O Split</div>', unsafe_allow_html=True)
            st.plotly_chart(
                chart_fo_donut(filtered),
                use_container_width=True,
                key="overview_fo_split",
            )

        st.markdown('<div class="sec-head">Top Earnings This Week</div>', unsafe_allow_html=True)
        render_top_earnings(top_earnings)

    # ── Tab 2: All Results ────────────────────────────────────────────────────
    with t2:
        st.markdown('<div class="sec-head">Upcoming Results</div>', unsafe_allow_html=True)
        table_search = st.text_input(
            "Search company",
            placeholder="Type company name or symbol...",
            key="results_inline_search",
        )
        table_filtered = _apply_filters(all_results, {**filters, "search": table_search})
        render_results_table(table_filtered)

    # ── Tab 3: F&O Spotlight ─────────────────────────────────────────────────
    with t3:
        fo_df = all_results[all_results["is_fo"].astype(bool)].copy() if not all_results.empty else pd.DataFrame()
        fo_df = _apply_filters(fo_df, {**filters, "fo_only": False})

        st.markdown(
            f'<div class="sec-head">F&O Companies — Next {LOOKAHEAD_DAYS} Days</div>',
            unsafe_allow_html=True,
        )

        if fo_df.empty:
            st.info("No F&O companies in the current filter.", icon="ℹ️")
        else:
            m1, m2, m3, _ = st.columns([1, 1, 1, 3])
            m1.metric("F&O Results", len(fo_df))
            m2.metric("Nifty 50", int(fo_df["is_nifty50"].sum()))
            m3.metric("Bank Nifty", int(fo_df["is_banknifty"].sum()))

            st.markdown("<br>", unsafe_allow_html=True)
            fo_df = fo_df.sort_values("result_date")
            fo_df["date_group"] = pd.to_datetime(fo_df["result_date"]).dt.strftime("%A, %d %b")
            date_order = fo_df.drop_duplicates("date_group")["date_group"].tolist()
            groups = [(d, fo_df[fo_df["date_group"] == d]) for d in date_order]
            cols   = st.columns(min(len(groups), 4))

            for i, (date_label, grp) in enumerate(groups):
                with cols[i % 4]:
                    rows_html = "".join(
                        f'<div style="padding:5px 0;border-bottom:1px solid #1E2340;'
                        f'font-size:0.82rem;color:#E8EAF0">'
                        f'{"🏆" if r["is_nifty50"] else "🎯"} {r["company_name"]}'
                        f'</div>'
                        for _, r in grp.iterrows()
                    )
                    st.markdown(
                        f"""<div style="background:#141727;border:1px solid #1E2340;
                                        border-radius:10px;padding:14px;margin-bottom:12px">
                                <div style="color:#8B8FA8;font-size:.7rem;text-transform:uppercase;
                                            letter-spacing:.07em;margin-bottom:8px">{date_label}</div>
                                {rows_html}
                            </div>""",
                        unsafe_allow_html=True,
                    )

    # ── Tab 4: Sector Intelligence ────────────────────────────────────────────
    with t4:
        st.markdown('<div class="sec-head">Sector Concentration</div>', unsafe_allow_html=True)

        if sector_conc.empty:
            st.info(
                "No sector data in the current date range. "
                "Sectors are only shown for F&O / index companies whose symbols "
                "matched the reference tables. Try widening the date range or "
                "removing the Sector filter.",
                icon="ℹ️",
            )
        else:
            sc1, sc2 = st.columns([2, 1])
            with sc1:
                st.plotly_chart(
                    chart_sector_bar(sector_conc),
                    use_container_width=True,
                    key="sectors_concentration",
                )
            with sc2:
                st.markdown("**Sector Summary**")
                display = sector_conc[["sector", "total_count", "fo_count"]].copy()
                display.columns = ["Sector", "Total", "F&O"]
                st.dataframe(display, use_container_width=True, height=380)

            st.markdown('<div class="sec-head">Importance by Date</div>', unsafe_allow_html=True)
            st.plotly_chart(
                chart_importance_scatter(filtered),
                use_container_width=True,
                key="sectors_importance_scatter",
            )

    # ── Tab 5: Pipeline Health ────────────────────────────────────────────────
    with t5:
        st.markdown('<div class="sec-head">Pipeline Health</div>', unsafe_allow_html=True)
        render_pipeline_health(pipeline_logs, last_run)

    # Footer
    st.markdown(
        '<div style="text-align:center;color:#8B8FA8;font-size:.72rem;'
        'margin-top:40px;padding-top:14px;border-top:1px solid #1E2340">'
        'F&O Earnings Intelligence Platform &nbsp;·&nbsp; '
        'GitHub Actions + CSV + Streamlit &nbsp;·&nbsp; '
        'Free forever &nbsp;·&nbsp; Not financial advice</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
