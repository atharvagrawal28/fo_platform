"""ui/components/tables.py — Table formatting and display."""

from datetime import datetime

import pandas as pd
import streamlit as st


def render_results_table(df: pd.DataFrame):
    """Render the main results table with export button."""
    if df.empty:
        st.info("No results found. Run the pipeline or adjust filters.", icon="ℹ️")
        return

    display = _format_for_display(df)

    n    = len(display)
    fo_n = int(df["is_fo"].astype(bool).sum()) if "is_fo" in df.columns else 0

    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(
            f'<span style="color:#8B8FA8;font-size:0.82rem;">'
            f'<b style="color:#E8EAF0">{n}</b> results &nbsp;|&nbsp; '
            f'F&O: <b style="color:#00C896">{fo_n}</b> &nbsp;|&nbsp; '
            f'Non-F&O: <b style="color:#FF6B6B">{n - fo_n}</b></span>',
            unsafe_allow_html=True,
        )
    with c2:
        st.download_button(
            "⬇ Export CSV",
            data=_to_csv(df),
            file_name=f"fo_earnings_{datetime.today().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.dataframe(
        display,
        use_container_width=True,
        height=460,
        column_config={
            "Result Date":    st.column_config.TextColumn(width="medium"),
            "Company":        st.column_config.TextColumn(width="large"),
            "F&O":            st.column_config.TextColumn(width="small"),
            "Sector":         st.column_config.TextColumn(width="medium"),
            "Importance":     st.column_config.ProgressColumn(
                                  min_value=0, max_value=120, width="small"),
            "Due In":         st.column_config.TextColumn(width="small"),
            "Index":          st.column_config.TextColumn(width="small"),
        },
    )


def render_top_earnings(df: pd.DataFrame):
    """Compact top-earnings table for the overview tab."""
    if df.empty:
        st.info("No high-impact earnings found.", icon="ℹ️")
        return

    for _, row in df.iterrows():
        badges = _index_badges(row)
        score  = int(row.get("importance_score", 0))
        date   = pd.to_datetime(row["result_date"]).strftime("%d %b")
        sector = row.get("sector") or "—"

        st.markdown(
            f"""
            <div style="display:flex;align-items:center;justify-content:space-between;
                        padding:9px 14px;margin-bottom:6px;
                        background:#141727;border:1px solid #1E2340;border-radius:8px;">
                <div>
                    <span style="font-size:0.88rem;font-weight:600;color:#E8EAF0">
                        {row['company_name']}
                    </span>
                    <span style="font-size:0.72rem;color:#8B8FA8;margin-left:8px">
                        {sector}
                    </span>
                    {badges}
                </div>
                <div style="text-align:right;min-width:80px">
                    <div style="font-size:0.78rem;color:#8B8FA8">{date}</div>
                    <div style="font-size:0.72rem;color:#00D4FF">Score: {score}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_pipeline_health(df: pd.DataFrame, last_run: dict):
    """Pipeline health panel."""
    if not last_run:
        st.warning(
            "No successful pipeline runs found yet. Trigger the GitHub Actions "
            "`Earnings Pipeline` workflow once; scheduled runs continue after that."
        )
        return

    # Status summary row
    status   = last_run.get("status", "unknown")
    source   = last_run.get("source_used", "—")
    fetched  = last_run.get("rows_fetched", 0)
    stored   = last_run.get("rows_stored", 0)
    duration = last_run.get("duration_seconds", 0)
    fallback = last_run.get("fallback_used", False)
    started  = last_run.get("started_at")

    status_color = "#00C896" if status == "success" else "#FF6B6B"

    st.markdown(
        f"""
        <div style="background:#141727;border:1px solid #1E2340;
                    border-radius:10px;padding:16px 20px;margin-bottom:16px;">
            <div style="display:flex;gap:32px;flex-wrap:wrap">
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Status</div>
                    <div style="color:{status_color};font-weight:600">{status.upper()}</div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Source</div>
                    <div style="color:#E8EAF0">{source}</div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Rows Fetched</div>
                    <div style="color:#E8EAF0">{fetched}</div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Rows Stored</div>
                    <div style="color:#E8EAF0">{stored}</div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Duration</div>
                    <div style="color:#E8EAF0">{duration:.1f}s</div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Fallback Used</div>
                    <div style="color:{'#FFB347' if fallback else '#00C896'}">{'Yes' if fallback else 'No'}</div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Last Run</div>
                    <div style="color:#E8EAF0;font-family:'IBM Plex Mono',monospace;font-size:0.82rem">
                        {pd.to_datetime(started).strftime("%d %b %Y %H:%M") if started else '—'}
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not df.empty:
        st.markdown("**Recent Pipeline Runs**")
        log_display = df[[
            "started_at", "status", "source_used",
            "rows_fetched", "rows_stored", "duration_seconds",
            "fallback_used", "validation_passed",
        ]].copy()
        log_display["started_at"] = pd.to_datetime(log_display["started_at"]).dt.strftime("%d %b %H:%M")
        log_display.columns = ["Started", "Status", "Source",
                                "Fetched", "Stored", "Duration(s)",
                                "Fallback", "Valid"]
        st.dataframe(log_display, use_container_width=True, height=280)


# ── Internal ──────────────────────────────────────────────────────────────────
def _format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["Result Date"] = pd.to_datetime(d["result_date"]).dt.strftime("%d %b %Y (%a)")
    d["Company"]     = d["company_name"]
    d["F&O"]         = d["is_fo"].map({True: "✅", False: "❌"}) if "is_fo" in d.columns else "—"
    d["Sector"]      = d.get("sector", "—").fillna("—")
    d["Importance"]  = d.get("importance_score", 0).fillna(0).astype(int)
    d["Due In"]      = d.get("days_remaining", 0).apply(_days_label)
    d["Index"]       = d.apply(_index_tag_text, axis=1)

    return d[["Result Date", "Company", "F&O", "Sector", "Importance", "Due In", "Index"]]


def _days_label(n) -> str:
    n = int(n) if n is not None else 0
    if n == 0:  return "🔴 Today"
    if n == 1:  return "🟡 Tomorrow"
    if n <= 3:  return f"🟠 {n}d"
    return            f"🟢 {n}d"


def _index_tag_text(row) -> str:
    tags = []
    if row.get("is_nifty50"):     tags.append("N50")
    if row.get("is_banknifty"):   tags.append("BNF")
    if row.get("is_nifty_next50"): tags.append("NN50")
    return " ".join(tags) if tags else "—"


def _index_badges(row) -> str:
    badges = []
    if row.get("is_nifty50"):
        badges.append('<span style="background:#FFB34722;color:#FFB347;padding:1px 6px;'
                      'border-radius:4px;font-size:0.65rem;margin-left:5px">N50</span>')
    if row.get("is_banknifty"):
        badges.append('<span style="background:#00C89622;color:#00C896;padding:1px 6px;'
                      'border-radius:4px;font-size:0.65rem;margin-left:5px">BNF</span>')
    if row.get("is_fo"):
        badges.append('<span style="background:#00D4FF22;color:#00D4FF;padding:1px 6px;'
                      'border-radius:4px;font-size:0.65rem;margin-left:5px">F&O</span>')
    return "".join(badges)


def _to_csv(df: pd.DataFrame) -> bytes:
    keep = [c for c in [
        "result_date", "company_name", "symbol", "sector",
        "is_fo", "is_nifty50", "is_banknifty", "market_cap_tier",
        "importance_score", "meeting_type", "source",
    ] if c in df.columns]
    return df[keep].to_csv(index=False).encode("utf-8")
