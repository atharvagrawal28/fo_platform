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
from database.oi_queries import (
    get_buildup_summary,
    get_earnings_oi_context,
    get_sector_buildup,
    get_strongest_signals,
)
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
from ui.components.oi_widgets import (
    chart_oi_quadrant,
    chart_sector_heatmap,
    render_buildup_cards,
    render_earnings_oi_panel,
    render_strongest_signals,
)
from ui.components.tables import (
    render_pipeline_health,
    render_results_table,
    render_today_alert,
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
    """Load all earnings dashboard data from CSV files."""
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


@st.cache_data(ttl=300)
def _load_oi_data():
    """Load OI / derivatives positioning data from CSV files."""
    from database.oi_queries import get_oi_snapshot
    return {
        "summary":         get_buildup_summary(),
        "sector_buildup":  get_sector_buildup(),
        "strongest":       get_strongest_signals(n=25),
        "earnings_ctx":    get_earnings_oi_context(),
        "snapshot":        get_oi_snapshot(),    # cached here, reused in F&O Spotlight + OI tab
    }


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _sidebar(sector_opts: pd.DataFrame, last_run: dict, kpis: dict = None) -> dict:
    with st.sidebar:
        # ── Today's Briefing box ──────────────────────────────────────────────
        if kpis:
            today_count   = kpis.get("today_count", 0)
            fo_week_count = kpis.get("fo_week_count", 0)
            fo_count      = kpis.get("fo_count", 0)
            n50_week      = kpis.get("nifty50_week_count", 0)
            today_str     = datetime.today().strftime("%A, %d %b")
            today_color   = "#FF6B6B" if today_count > 0 else "#8B8FA8"
            st.markdown(
                f"""
                <div style="background:#0D1524;border:1px solid #00D4FF44;
                            border-left:3px solid #00D4FF;border-radius:8px;
                            padding:12px 14px;margin-bottom:14px">
                    <div style="font-size:0.68rem;color:#8B8FA8;
                                text-transform:uppercase;letter-spacing:.07em;
                                margin-bottom:6px">📅 Today's Briefing</div>
                    <div style="font-size:0.82rem;color:#E8EAF0;
                                font-weight:600;margin-bottom:8px">{today_str}</div>
                    <div style="font-size:0.75rem;color:#8B8FA8;line-height:2">
                        Today: &nbsp;<b style="color:{today_color}">{today_count}</b> results<br>
                        This week F&amp;O: &nbsp;<b style="color:#00C896">{fo_week_count}</b><br>
                        Nifty 50 this week: &nbsp;<b style="color:#FFB347">{n50_week}</b>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

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

        _is_weekend = datetime.today().weekday() >= 5
        st.markdown(
            '<div style="font-size:0.68rem;color:#8B8FA8;text-align:center;margin-top:4px">'
            + ('⏸ Weekend — resumes Monday 8AM IST' if _is_weekend else 'Pipeline runs 8AM &amp; 4:30PM IST weekdays')
            + '</div>',
            unsafe_allow_html=True,
        )

        # Pipeline status mini-panel
        if last_run:
            status  = last_run.get("status", "unknown")
            # On weekends a Friday "success" should still show green
            s_color = "#00C896" if status == "success" else ("#FFB347" if _is_weekend else "#FF6B6B")
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

    return {
        "search": "", "fo_only": fo_only, "n50_only": n50_only,
        "sector": selected_sector, "start": start, "end": end,
    }


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
    rows_text = f"{db_rows:,} companies tracked" if db_rows else "—"
    age_text  = "unknown age" if age_hours is None else f"{age_hours:.1f}h old"

    # 3-tier freshness: <12h green · 12-24h amber · >24h red+banner
    # Pipeline only runs Mon–Fri — never flag stale on weekends
    is_weekend = datetime.today().weekday() >= 5  # Saturday=5, Sunday=6

    if is_weekend:
        freshness_label = "● Weekend"
        freshness_color = "#8B8FA8"
        is_stale = False
    elif age_hours is None:
        freshness_label = "UNKNOWN"
        freshness_color = "#8B8FA8"
        is_stale = False
    elif age_hours < 12:
        freshness_label = "● CURRENT DATA"
        freshness_color = "#00C896"
        is_stale = False
    elif age_hours < 24:
        freshness_label = f"● {age_hours:.1f}h old"
        freshness_color = "#FFB347"
        is_stale = False
    else:
        freshness_label = f"⚠ DATA STALE — {age_hours:.0f}h old"
        freshness_color = "#FF6B6B"
        is_stale = True

    st.markdown(
        f"""
        <div style="padding:16px 0 20px;border-bottom:1px solid #1E2340;
                    margin-bottom:{'8px' if is_stale else '20px'};
                    display:flex;justify-content:space-between;
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
                             background:rgba(0,0,0,.2);
                             border:1px solid {freshness_color};
                             color:{freshness_color};padding:2px 10px;
                             border-radius:20px;font-size:.7rem;
                             font-weight:600;letter-spacing:.06em">{freshness_label}</span>
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

    # Stale data warning bar (only when >24h old)
    if is_stale:
        st.markdown(
            f"""
            <div style="background:#FF6B6B18;border:1px solid #FF6B6B55;
                        border-radius:8px;padding:10px 16px;margin-bottom:16px;
                        font-size:0.82rem;color:#FF6B6B">
                ⚠️ Pipeline last ran <b>{age_hours:.0f}h ago</b>. Data may be outdated.
                Check <b>GitHub Actions → Earnings Pipeline</b> if this persists.
                Pipeline should run at 8:00 AM and 4:30 PM IST on weekdays.
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
        data    = _load_all_data(days=LOOKAHEAD_DAYS)
        oi_data = _load_oi_data()

    all_results   = data["all_results"]
    kpis          = data["kpis"]
    daily_dist    = data["daily_dist"]
    sector_conc   = data["sector_conc"]
    top_earnings  = data["top_earnings"]
    pipeline_logs = data["pipeline_logs"]
    last_run      = data["last_run"]
    sector_opts   = data["sector_opts"]

    db_rows = len(all_results) if not all_results.empty else 0

    # Sidebar (needs sector list, last run, and kpis for the briefing box)
    filters = _sidebar(sector_opts, last_run, kpis)

    # Header
    _header(last_run, db_rows=db_rows)

    # Empty state
    if all_results.empty and kpis["total"] == 0:
        _show_empty_data()

    # Apply sidebar filters
    filtered = _apply_filters(all_results, filters)

    # Today's results (for the alert card and briefing box)
    from datetime import date as _date
    today_ts     = pd.Timestamp(_date.today())
    today_results = (
        all_results[all_results["result_date"] == today_ts]
        .sort_values(["importance_score", "is_fo"], ascending=[False, False])
        .reset_index(drop=True)
    ) if not all_results.empty else pd.DataFrame()

    # Unpack OI data
    oi_summary       = oi_data["summary"]
    oi_sector        = oi_data["sector_buildup"]
    oi_strongest     = oi_data["strongest"]
    oi_earnings_ctx  = oi_data["earnings_ctx"]
    oi_snap          = oi_data["snapshot"]

    # ── Tabs ──────────────────────────────────────────────────────────────────
    t1, t2, t3, t4, t5, t6 = st.tabs([
        "📊 Overview",
        "📋 All Results",
        "🎯 F&O Spotlight",
        "🏭 Sectors",
        "📡 OI Positioning",
        "⚙️ Pipeline Health",
    ])

    # ── Tab 1: Overview ───────────────────────────────────────────────────────
    with t1:
        # 1. Today's alert card — only shown when companies report today
        render_today_alert(today_results)

        # 2. KPI cards
        render_kpi_row(kpis)

        # 3. Top Earnings — moved above charts (highest daily-use value)
        st.markdown('<div class="sec-head">Top Earnings This Week</div>', unsafe_allow_html=True)
        render_top_earnings(top_earnings)

        # 4. Charts row
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
            st.markdown(
                '<div style="background:#141727;border:1px solid #1E2340;border-radius:10px;'
                'padding:40px;text-align:center;color:#8B8FA8;font-size:0.88rem">'
                'No F&O companies match your current filters.<br>'
                '<span style="font-size:0.78rem">Try removing the sector or date filter.</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            # Summary row
            n50_count  = int(fo_df["is_nifty50"].sum())
            bnf_count  = int(fo_df["is_banknifty"].sum())
            total_fo   = len(fo_df)

            # "Next result" — earliest reporting date
            next_row = fo_df.sort_values("result_date").iloc[0]
            next_name = next_row.get("symbol") or next_row.get("company_name", "")
            next_date_ts = pd.to_datetime(next_row["result_date"])
            if next_date_ts.date() == today_ts.date():
                next_date_str = "Today"
            elif next_date_ts.date() == (today_ts + pd.Timedelta(days=1)).date():
                next_date_str = "Tomorrow"
            else:
                next_date_str = next_date_ts.strftime("%d %b")

            st.markdown(
                f'<div style="font-size:0.78rem;color:#8B8FA8;margin-bottom:14px">'
                f'🎯 <b style="color:#E8EAF0">{total_fo}</b> F&amp;O companies reporting &nbsp;|&nbsp; '
                f'🏆 <b style="color:#FFB347">{n50_count}</b> Nifty 50 &nbsp;|&nbsp; '
                f'🏦 <b style="color:#00C896">{bnf_count}</b> Bank Nifty &nbsp;|&nbsp; '
                f'📅 Next: <b style="color:#00D4FF">{next_name}</b> on {next_date_str}'
                f'</div>',
                unsafe_allow_html=True,
            )

            fo_df = fo_df.sort_values("result_date")
            fo_df["date_group"] = pd.to_datetime(fo_df["result_date"]).dt.strftime("%A, %d %b")
            date_order = fo_df.drop_duplicates("date_group")["date_group"].tolist()
            groups = [(d, fo_df[fo_df["date_group"] == d]) for d in date_order]
            cols   = st.columns(min(len(groups), 4))

            for i, (date_label, grp) in enumerate(groups):
                with cols[i % 4]:
                    cards_html = ""
                    for _, r in grp.iterrows():
                        score   = int(r.get("importance_score", 0) or 0)
                        sector  = r.get("sector", "") or ""
                        cap     = r.get("market_cap_tier", "") or ""
                        symbol  = r.get("symbol", "") or ""
                        days_r  = int(r.get("days_remaining", 0) or 0)
                        n50_ico = "🏆" if r.get("is_nifty50") else ""
                        bnf_ico = "🏦" if r.get("is_banknifty") else ""

                        # Border color: red=today, amber=tomorrow, green=3+ days
                        if days_r == 0:
                            border_col = "#FF6B6B"
                        elif days_r == 1:
                            border_col = "#FFB347"
                        else:
                            border_col = "#00C896"

                        meta_parts = [p for p in [sector, cap] if p]
                        meta_line  = " · ".join(meta_parts)

                        score_html = (
                            f'<span style="color:#00D4FF;font-size:0.68rem">'
                            f'Score: {score}</span>'
                            if score > 0 else ""
                        )

                        # OI data if available for this symbol
                        oi_html = ""
                        if not oi_snap.empty and symbol:
                            oi_row = oi_snap[oi_snap["symbol"] == symbol]
                            if not oi_row.empty:
                                p_chg  = float(oi_row.iloc[0].get("price_chg_pct", 0) or 0)
                                oi_chg = float(oi_row.iloc[0].get("oi_chg_pct", 0) or 0)
                                pc = "#00C896" if p_chg >= 0 else "#FF6B6B"
                                oc = "#00C896" if oi_chg > 0 else "#FF6B6B"
                                oi_html = (
                                    f'<div style="font-size:0.62rem;margin-top:4px;'
                                    f'border-top:1px solid #1E2340;padding-top:4px">'
                                    f'<span style="color:{pc}">P {p_chg:+.1f}%</span>'
                                    f' &nbsp;·&nbsp; '
                                    f'<span style="color:{oc}">OI {oi_chg:+.1f}%</span>'
                                    f'</div>'
                                )

                        cards_html += (
                            f'<div style="border:1px solid #1E2340;'
                            f'border-left:3px solid {border_col};'
                            f'border-radius:6px;padding:8px 10px;margin-bottom:6px;'
                            f'background:#0D0F1C">'
                            f'<div style="display:flex;justify-content:space-between;'
                            f'align-items:flex-start">'
                            f'<div style="flex:1;min-width:0">'
                            f'<div style="font-size:0.82rem;font-weight:600;color:#E8EAF0;'
                            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                            f'{n50_ico}{bnf_ico} {r["company_name"]}</div>'
                            f'<div style="font-size:0.65rem;color:#8B8FA8;margin-top:1px">'
                            f'{symbol}</div>'
                            + (f'<div style="font-size:0.63rem;color:#8B8FA8;margin-top:1px">'
                               f'{meta_line}</div>' if meta_line else "")
                            + f'</div>'
                            f'<div style="padding-left:8px;flex-shrink:0">'
                            f'{score_html}</div>'
                            f'</div>'
                            f'{oi_html}'
                            f'</div>'
                        )

                    st.markdown(
                        f'<div style="background:#141727;border:1px solid #1E2340;'
                        f'border-radius:10px;padding:14px;margin-bottom:12px">'
                        f'<div style="color:#8B8FA8;font-size:.7rem;text-transform:uppercase;'
                        f'letter-spacing:.07em;margin-bottom:8px">{date_label}</div>'
                        f'{cards_html}</div>',
                        unsafe_allow_html=True,
                    )

    # ── Tab 4: Sector Intelligence ────────────────────────────────────────────
    with t4:
        st.markdown(
            '<div class="sec-head">Sector Concentration — F&O Universe This Week</div>',
            unsafe_allow_html=True,
        )

        if sector_conc.empty:
            st.markdown(
                '<div style="background:#141727;border:1px solid #1E2340;border-radius:10px;'
                'padding:32px;text-align:center;color:#8B8FA8;font-size:0.88rem">'
                'No F&O sector data in the current date range.<br>'
                '<span style="font-size:0.78rem">Try widening the date range or removing the Sector filter.</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            n_stocks  = int(sector_conc["total_count"].sum())
            n_sectors = len(sector_conc)
            st.markdown(
                f'<div style="font-size:0.72rem;color:#8B8FA8;margin-bottom:14px">'
                f'Showing <b style="color:#E8EAF0">{n_stocks}</b> F&amp;O stocks across '
                f'<b style="color:#E8EAF0">{n_sectors}</b> sectors &nbsp;·&nbsp; '
                f'<span style="color:#8B8FA8">Non-F&amp;O companies excluded — '
                f'not in the tracked F&amp;O universe</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

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
                display.columns = ["Sector", "F&O Count", "F&O ✓"]
                st.dataframe(display, use_container_width=True, height=380)

            st.markdown('<div class="sec-head">Importance by Date (F&O)</div>', unsafe_allow_html=True)
            # Only pass F&O stocks to the scatter chart — consistent with the sector focus
            fo_filtered = filtered[filtered["is_fo"].astype(bool)] if not filtered.empty else filtered
            st.plotly_chart(
                chart_importance_scatter(fo_filtered),
                use_container_width=True,
                key="sectors_importance_scatter",
            )

    # ── Tab 5: OI Positioning Intelligence ───────────────────────────────────
    with t5:
        st.markdown(
            '<div class="sec-head">Derivatives Positioning Intelligence</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div style="font-size:0.72rem;color:#8B8FA8;margin-bottom:16px">'
            'Observational analysis of futures open interest activity. '
            'Positioning classifications are based on price & OI directional changes. '
            'Not financial advice.</div>',
            unsafe_allow_html=True,
        )

        if oi_summary.get("total", 0) == 0:
            st.info(
                "OI data not yet available. The pipeline fetches NSE F&O Bhavcopy "
                "after market close (~6PM IST). Trigger **Actions → Earnings Pipeline** "
                "once the market closes to populate this tab.",
                icon="📡",
            )
        else:
            # Row 1: Summary cards
            render_buildup_cards(oi_summary)

            st.markdown("---")

            # Row 2: Quadrant scatter + Pre-Earnings context
            col_q, col_e = st.columns([3, 2])
            with col_q:
                st.markdown(
                    '<div class="sec-head">Positioning Quadrant</div>',
                    unsafe_allow_html=True,
                )
                st.plotly_chart(
                    chart_oi_quadrant(oi_snap),
                    use_container_width=True,
                    key="oi_quadrant",
                )

            with col_e:
                st.markdown(
                    '<div class="sec-head">Pre-Earnings Positioning</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div style="font-size:0.68rem;color:#8B8FA8;margin-bottom:10px">'
                    'F&O stocks reporting results this week + current derivatives activity</div>',
                    unsafe_allow_html=True,
                )
                render_earnings_oi_panel(oi_earnings_ctx)

            st.markdown("---")

            # Row 3: Sector heatmap + Strongest signals
            col_s, col_t = st.columns([2, 3])
            with col_s:
                st.markdown(
                    '<div class="sec-head">Sector Positioning</div>',
                    unsafe_allow_html=True,
                )
                st.plotly_chart(
                    chart_sector_heatmap(oi_sector),
                    use_container_width=True,
                    key="oi_sector_heatmap",
                )

            with col_t:
                st.markdown(
                    '<div class="sec-head">Strongest Positioning Shifts</div>',
                    unsafe_allow_html=True,
                )
                render_strongest_signals(oi_strongest)

    # ── Tab 6: Pipeline Health ────────────────────────────────────────────────
    with t6:
        st.markdown('<div class="sec-head">Pipeline Health</div>', unsafe_allow_html=True)
        render_pipeline_health(pipeline_logs, last_run)

    # Footer
    st.markdown(
        '<div style="text-align:center;color:#8B8FA8;font-size:.72rem;'
        'margin-top:40px;padding-top:14px;border-top:1px solid #1E2340">'
        'F&O Earnings Intelligence Platform &nbsp;·&nbsp; '
        'GitHub Actions + CSV + Streamlit &nbsp;·&nbsp; '
        'Free forever &nbsp;·&nbsp; Not financial advice'
        '<br><br>'
        'Built by&nbsp;'
        '<a href="https://www.linkedin.com/in/atharv-agrawal-295743233" '
        'target="_blank" '
        'style="color:#00D4FF;text-decoration:none;font-weight:600;">'
        'Atharv Agrawal'
        '</a>'
        '</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
