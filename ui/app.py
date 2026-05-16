"""
ui/app.py — F&O Earnings Intelligence Platform
================================================
Presentation-only Streamlit dashboard.
Reads PostgreSQL. Zero scraping. Zero heavy processing.

Run: streamlit run ui/app.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

sys.path.insert(0, str(Path(__file__).parent.parent))

from configs.settings import (
    DATABASE_URL,
    LOOKAHEAD_DAYS,
)
from database.connection import ensure_connected, get_streamlit_connection
from database.queries import (
    get_daily_distribution,
    get_kpis,
    get_last_pipeline_run,
    get_pipeline_health,
    get_sector_options,
    get_sector_concentration,
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

AUTO_REFRESH_SECONDS = 900

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


# ── DB connection (cached, health-checked before every query) ─────────────────
@st.cache_resource
def _connection_holder():
    if not DATABASE_URL:
        return {"conn": None}
    try:
        return {"conn": get_streamlit_connection(DATABASE_URL)}
    except Exception:
        return {"conn": None}


def _safe_conn():
    if not DATABASE_URL:
        return None

    holder = _connection_holder()
    try:
        holder["conn"] = ensure_connected(holder.get("conn"), DATABASE_URL)
        return holder["conn"]
    except Exception as e:
        holder["conn"] = None
        st.error(f"❌ Database connection failed: {e}")
        return None


def _query_db(query_fn, default, *args, **kwargs):
    conn = _safe_conn()
    if not conn:
        return default() if callable(default) else default

    try:
        return query_fn(conn, *args, **kwargs)
    except Exception:
        holder = _connection_holder()
        try:
            if holder.get("conn"):
                holder["conn"].close()
        except Exception:
            pass

        holder["conn"] = None
        conn = _safe_conn()
        if not conn:
            return default() if callable(default) else default
        return query_fn(conn, *args, **kwargs)


def _wire_auto_refresh():
    if st_autorefresh:
        st_autorefresh(
            interval=AUTO_REFRESH_SECONDS * 1000,
            key="fo_platform_auto_refresh",
        )


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _sidebar() -> dict:
    with st.sidebar:
        st.markdown("## ⚙️ Filters")
        st.markdown("---")

        fo_only = st.checkbox("F&O stocks only")
        n50_only = st.checkbox("Nifty 50 only")

        st.markdown("**Sector**")
        conn = _safe_conn()
        sector_options = ["All"]
        if conn:
            sec_df = _query_db(get_sector_options, pd.DataFrame)
            if not sec_df.empty:
                sector_options += sorted(sec_df["sector"].dropna().astype(str).unique())
        selected_sector = st.selectbox("Sector", sector_options, label_visibility="collapsed")

        st.markdown("**Date Range**")
        today    = datetime.today().date()
        max_date = today + timedelta(days=LOOKAHEAD_DAYS)
        c1, c2   = st.columns(2)
        with c1: start = st.date_input("From", value=today, min_value=today, max_value=max_date)
        with c2: end   = st.date_input("To",   value=max_date, min_value=today, max_value=max_date)

        st.markdown("---")
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_resource.clear()
            st.cache_data.clear()
            st.rerun()

        # Pipeline status mini-panel
        if conn:
            last = _query_db(get_last_pipeline_run, {})
            if last:
                status = last.get("status", "unknown")
                s_color = "#00C896" if status == "success" else "#FF6B6B"
                ts = pd.to_datetime(last.get("started_at")).strftime("%d %b %H:%M") if last.get("started_at") else "—"
                st.markdown(
                    f"""
                    <div style="font-size:0.72rem;color:#8B8FA8;line-height:2;margin-top:8px">
                    🟢 DB: <b style="color:#00C896">Connected</b><br>
                    ⚙️ Pipeline: <b style="color:{s_color}">{status}</b><br>
                    🕐 Last run: <b style="color:#E8EAF0">{ts}</b><br>
                    📡 Source: <b style="color:#E8EAF0">{last.get('source_used','—')}</b>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    return dict(
        search="", fo_only=fo_only, n50_only=n50_only,
        sector=selected_sector, start=start, end=end,
    )


# ── Header ────────────────────────────────────────────────────────────────────
def _header(last_run: dict):
    ts = "—"
    if last_run and last_run.get("started_at"):
        ts = pd.to_datetime(last_run["started_at"]).strftime("%d %b %Y, %H:%M IST")
    source = last_run.get("source_used", "—") if last_run else "—"
    rows   = last_run.get("rows_stored", 0) if last_run else 0

    st.markdown(
        f"""
        <div style="padding:16px 0 20px;border-bottom:1px solid #1E2340;
                    margin-bottom:20px;display:flex;justify-content:space-between;
                    align-items:flex-end;flex-wrap:wrap;gap:8px">
            <div>
                <span style="font-size:1.8rem;font-weight:700;
                             letter-spacing:-.02em;color:#E8EAF0">
                    📈 F&O Earnings Intelligence
                </span>
                <span style="display:inline-block;margin-left:10px;
                             background:rgba(0,212,255,.12);
                             border:1px solid rgba(0,212,255,.3);
                             color:#00D4FF;padding:2px 10px;
                             border-radius:20px;font-size:.7rem;
                             font-weight:600;letter-spacing:.08em">LIVE DB</span>
            </div>
            <div style="font-size:0.75rem;color:#8B8FA8;
                        font-family:'IBM Plex Mono',monospace;text-align:right">
                Last refresh: {ts}<br>
                Source: {source} &nbsp;|&nbsp; {rows} rows in DB
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
    if f["search"].strip():
        term = f["search"].strip()
        mask = d["company_name"].str.contains(term, case=False, na=False)
        if "symbol" in d.columns:
            mask = mask | d["symbol"].str.contains(term, case=False, na=False)
        d = d[mask]
    if f["fo_only"]:
        d = d[d["is_fo"] == True]
    if f["n50_only"]:
        d = d[d["is_nifty50"] == True]
    if f["sector"] != "All":
        d = d[d["sector"] == f["sector"]]
    if f["start"]:
        d = d[d["result_date"] >= pd.Timestamp(f["start"])]
    if f["end"]:
        d = d[d["result_date"] <= pd.Timestamp(f["end"])]
    return d.reset_index(drop=True)


# ── No-DB fallback page ───────────────────────────────────────────────────────
def _show_no_db():
    st.error(
        "**Database not connected.**\n\n"
        "Set `DATABASE_URL` in `.streamlit/secrets.toml` (Streamlit Cloud) "
        "or in your `.env` file (local), then restart the app.",
        icon="🔌",
    )
    st.code("""
# .streamlit/secrets.toml (for Streamlit Cloud)
DATABASE_URL = "postgresql://user:pass@host/db?sslmode=require"

# .env (for local development)
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
    """)
    st.stop()


# ── Empty-DB state ────────────────────────────────────────────────────────────
def _show_empty_db():
    st.warning(
        "**Database is connected, but the cloud pipeline has not written data yet.**\n\n"
        "No local scraping is needed. Add `DATABASE_URL` as a GitHub Actions "
        "secret, then trigger **Actions → Earnings Pipeline → Run workflow** "
        "once. After that, GitHub Actions keeps Neon updated automatically and "
        "this dashboard auto-refreshes to pick up the next successful run.",
        icon="📭",
    )


def _empty_kpis() -> dict:
    return {
        "total": 0,
        "fo_count": 0,
        "today_count": 0,
        "week_count": 0,
        "nifty50_count": 0,
        "fo_pct": 0.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    _css()
    _wire_auto_refresh()

    conn = _safe_conn()
    if not conn:
        _show_no_db()

    # Load all data
    with st.spinner("Loading from database…"):
        all_results   = _query_db(get_upcoming_results, pd.DataFrame)
        kpis          = _query_db(get_kpis, _empty_kpis)
        daily_dist    = _query_db(get_daily_distribution, pd.DataFrame)
        sector_conc   = _query_db(get_sector_concentration, pd.DataFrame)
        top_earnings  = _query_db(get_top_earnings, pd.DataFrame, limit=10)
        pipeline_logs = _query_db(get_pipeline_health, pd.DataFrame, limit=10)
        last_run      = _query_db(get_last_pipeline_run, {})

    # Sidebar filters
    filters = _sidebar()

    # Header
    _header(last_run)

    # Empty DB state
    if all_results.empty and kpis["total"] == 0:
        _show_empty_db()

    # Apply filters
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
        fo_df = all_results[all_results["is_fo"] == True].copy() if not all_results.empty else pd.DataFrame()
        fo_df = _apply_filters(fo_df, {**filters, "fo_only": False})

        st.markdown('<div class="sec-head">F&O Companies — Next 7 Days</div>', unsafe_allow_html=True)

        if fo_df.empty:
            st.info("No F&O companies in the current filter.", icon="ℹ️")
        else:
            m1, m2, m3, _ = st.columns([1, 1, 1, 3])
            m1.metric("F&O Results", len(fo_df))
            m2.metric("Nifty 50", int(fo_df["is_nifty50"].sum()))
            m3.metric("Bank Nifty", int(fo_df["is_banknifty"].sum()))

            st.markdown("<br>", unsafe_allow_html=True)
            fo_df["date_group"] = pd.to_datetime(fo_df["result_date"]).dt.strftime("%A, %d %b")
            groups = list(fo_df.groupby("date_group", sort=False))
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
            st.info("No sector data. Ensure fo_universe is seeded and pipeline has run.", icon="ℹ️")
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
        'PostgreSQL + GitHub Actions + Streamlit &nbsp;·&nbsp; '
        'Not financial advice</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
