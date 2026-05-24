"""ui/components/tables.py — Table formatting and display."""

from datetime import datetime, date

import pandas as pd
import streamlit as st


# ── Today's Alert Card ────────────────────────────────────────────────────────
def render_today_alert(df: pd.DataFrame):
    """
    Amber alert card shown at the top of Overview when companies report today.
    df: earnings rows already filtered to result_date == today.
    Renders nothing if df is empty.
    """
    if df.empty:
        return

    today_str    = datetime.today().strftime("%A, %d %b %Y")
    is_fo_mask   = df["is_fo"].astype(bool) if "is_fo" in df.columns else pd.Series([False] * len(df), index=df.index)
    fo_today     = df[is_fo_mask]
    fo_count     = len(fo_today)
    total_count  = len(df)
    non_fo_count = total_count - fo_count

    border_color = "#FFB347" if fo_count > 0 else "#2A2D40"
    icon         = "🔴" if fo_count > 0 else "📅"

    # Build company pills (F&O companies first, then +N others)
    pills = []
    for _, r in fo_today.head(8).iterrows():
        sym = r.get("symbol") or r.get("company_name", "?")
        pills.append(
            f'<span style="background:#FFB34722;color:#FFB347;padding:3px 10px;'
            f'border-radius:4px;font-size:0.75rem;font-weight:600;white-space:nowrap">'
            f'{sym}</span>'
        )
    if len(fo_today) > 8:
        pills.append(
            f'<span style="color:#8B8FA8;font-size:0.72rem">'
            f'+{len(fo_today) - 8} more F&amp;O</span>'
        )
    if non_fo_count > 0:
        pills.append(
            f'<span style="color:#8B8FA8;font-size:0.72rem">'
            f'+{non_fo_count} other companies</span>'
        )

    if not pills:
        pills.append(
            f'<span style="color:#8B8FA8;font-size:0.75rem">'
            f'{total_count} companies reporting</span>'
        )

    pills_html = " ".join(pills)

    st.markdown(
        f"""
        <div style="background:#141727;
                    border:1px solid {border_color};
                    border-left:4px solid {border_color};
                    border-radius:10px;padding:14px 20px;margin-bottom:16px">
            <div style="display:flex;justify-content:space-between;
                        align-items:flex-start;flex-wrap:wrap;gap:12px">
                <div style="flex:1">
                    <div style="font-size:0.72rem;color:#8B8FA8;
                                text-transform:uppercase;letter-spacing:.07em;
                                margin-bottom:8px">
                        {icon} Results Today — {today_str}
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
                        {pills_html}
                    </div>
                </div>
                <div style="text-align:right;font-size:0.75rem;color:#8B8FA8;
                            padding-top:2px;flex-shrink:0">
                    <b style="color:#E8EAF0;font-size:1.1rem">{total_count}</b> total<br>
                    <b style="color:#00C896">{fo_count}</b> F&amp;O
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Main Results Table ────────────────────────────────────────────────────────
def render_results_table(df: pd.DataFrame):
    """Render the main results table with export button."""
    if df.empty:
        st.markdown(
            '<div style="background:#141727;border:1px solid #1E2340;border-radius:10px;'
            'padding:40px;text-align:center;color:#8B8FA8;font-size:0.88rem">'
            'No results found. Try removing a filter or widening the date range.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Sort: importance DESC then date ASC → F&O stocks float to top
    sort_df = df.copy()
    if "importance_score" in sort_df.columns and "result_date" in sort_df.columns:
        sort_df = sort_df.sort_values(
            ["importance_score", "result_date"],
            ascending=[False, True],
        ).reset_index(drop=True)

    display = _format_for_display(sort_df)

    total_n  = len(sort_df)
    fo_n     = int(sort_df["is_fo"].astype(bool).sum()) if "is_fo" in sort_df.columns else 0
    non_fo_n = total_n - fo_n

    today_ts    = pd.Timestamp(date.today())
    tomorrow_ts = today_ts + pd.Timedelta(days=1)
    today_n = int((sort_df["result_date"] == today_ts).sum()) if "result_date" in sort_df.columns else 0
    tmrw_n  = int((sort_df["result_date"] == tomorrow_ts).sum()) if "result_date" in sort_df.columns else 0
    week_n  = int(
        ((sort_df["result_date"] >= today_ts) & (sort_df["result_date"] <= today_ts + pd.Timedelta(days=6))).sum()
    ) if "result_date" in sort_df.columns else 0

    # Two-line stats header
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(
            f'<div style="font-size:0.8rem;color:#8B8FA8;margin-bottom:3px">'
            f'<b style="color:#E8EAF0">{total_n}</b> total results'
            f' &nbsp;|&nbsp; F&O: <b style="color:#00C896">{fo_n}</b> (sorted to top)'
            f' &nbsp;|&nbsp; Non-F&O: <b style="color:#8B8FA8">{non_fo_n}</b>'
            f'</div>'
            f'<div style="font-size:0.75rem;color:#8B8FA8;margin-bottom:8px">'
            f'Today: <b style="color:#FF6B6B">{today_n}</b>'
            f' &nbsp;|&nbsp; Tomorrow: <b style="color:#FFB347">{tmrw_n}</b>'
            f' &nbsp;|&nbsp; This week: <b style="color:#00D4FF">{week_n}</b>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.download_button(
            "⬇ Export CSV",
            data=_to_csv(sort_df),
            file_name=f"FO_Earnings_{datetime.today().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.dataframe(
        display,
        use_container_width=True,
        height=600,
        column_config={
            "Result Date": st.column_config.TextColumn(width="medium"),
            "Symbol":      st.column_config.TextColumn(width="small"),
            "Company":     st.column_config.TextColumn(width="large"),
            "F&O":         st.column_config.TextColumn(width="small"),
            "Sector":      st.column_config.TextColumn(width="medium"),
            "Impact":      st.column_config.TextColumn(width="small"),
            "Due In":      st.column_config.TextColumn(width="small"),
            "Index":       st.column_config.TextColumn(width="small"),
        },
    )


# ── Top Earnings Card List ────────────────────────────────────────────────────
def render_top_earnings(df: pd.DataFrame):
    """Compact top-earnings cards for the overview tab."""
    if df.empty:
        st.info("No high-impact earnings found.", icon="ℹ️")
        return

    today_ts    = pd.Timestamp(date.today())
    tomorrow_ts = today_ts + pd.Timedelta(days=1)

    for _, row in df.iterrows():
        badges  = _index_badges(row)
        score   = int(row.get("importance_score", 0))
        rd      = pd.to_datetime(row["result_date"])
        sector  = row.get("sector") or "—"
        symbol  = row.get("symbol") or ""
        cap     = row.get("market_cap_tier") or ""

        # Human-friendly date label
        if rd.date() == today_ts.date():
            date_label = "🔴 Today"
            date_color = "#FF6B6B"
        elif rd.date() == tomorrow_ts.date():
            date_label = "🟡 Tomorrow"
            date_color = "#FFB347"
        else:
            date_label = rd.strftime("%a %d %b")
            date_color = "#8B8FA8"

        # Importance pill
        if score > 60:
            imp_html = '<span style="background:#FF6B6B22;color:#FF6B6B;padding:1px 7px;border-radius:4px;font-size:0.65rem;font-weight:600">HIGH</span>'
        elif score >= 30:
            imp_html = '<span style="background:#FFB34722;color:#FFB347;padding:1px 7px;border-radius:4px;font-size:0.65rem;font-weight:600">MED</span>'
        else:
            imp_html = f'<span style="font-size:0.68rem;color:#00D4FF">Score: {score}</span>'

        meta_parts = [p for p in [sector, cap] if p and p != "—"]
        meta_line  = " · ".join(meta_parts) if meta_parts else sector

        st.markdown(
            f"""
            <div style="display:flex;align-items:center;justify-content:space-between;
                        padding:9px 14px;margin-bottom:6px;
                        background:#141727;border:1px solid #1E2340;border-radius:8px;">
                <div style="flex:1;min-width:0">
                    <div>
                        <span style="font-size:0.88rem;font-weight:600;color:#E8EAF0">
                            {row['company_name']}
                        </span>
                        <span style="font-size:0.7rem;color:#8B8FA8;margin-left:6px">
                            {symbol}
                        </span>
                        {badges}
                    </div>
                    <div style="font-size:0.68rem;color:#8B8FA8;margin-top:2px">
                        {meta_line}
                    </div>
                </div>
                <div style="text-align:right;min-width:90px;padding-left:10px;flex-shrink:0">
                    <div style="font-size:0.78rem;color:{date_color};font-weight:600">
                        {date_label}
                    </div>
                    <div style="margin-top:3px">{imp_html}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Pipeline Health Panel ─────────────────────────────────────────────────────
def render_pipeline_health(df: pd.DataFrame, last_run: dict):
    """Pipeline health panel."""
    if not last_run:
        st.warning(
            "No successful pipeline runs found yet. Trigger the GitHub Actions "
            "`Earnings Pipeline` workflow once; scheduled runs continue after that."
        )
        return

    status   = last_run.get("status", "unknown")
    source   = last_run.get("source_used", "—")
    fetched  = last_run.get("rows_fetched", 0)
    stored   = last_run.get("rows_stored", 0)
    duration = last_run.get("duration_seconds", 0) or 0
    fallback = last_run.get("fallback_used", False)
    started  = last_run.get("started_at")

    status_color  = "#00C896" if status == "success" else ("#FFB347" if status == "partial" else "#FF6B6B")
    fallback_color = "#FFB347" if fallback else "#00C896"

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
                    <div style="color:{fallback_color}">{'Yes' if fallback else 'No'}</div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Last Run</div>
                    <div style="color:#E8EAF0;font-family:'IBM Plex Mono',monospace;font-size:0.82rem">
                        {pd.to_datetime(started).strftime("%d %b %Y %H:%M") if started else '—'}
                    </div>
                </div>
                <div>
                    <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase">Next Scheduled</div>
                    <div style="color:#8B8FA8;font-size:0.78rem">8:00 AM &amp; 4:30 PM IST (weekdays)</div>
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
        log_display["started_at"]       = pd.to_datetime(log_display["started_at"]).dt.strftime("%d %b %H:%M")
        log_display["duration_seconds"] = log_display["duration_seconds"].apply(
            lambda x: f"{float(x):.1f}s" if pd.notna(x) else "—"
        )
        log_display["status"] = log_display["status"].apply(
            lambda s: "✅ " + s if s == "success" else ("⚠ " + s if s == "partial" else "❌ " + s)
        )
        log_display.columns = ["Started", "Status", "Source",
                               "Fetched", "Stored", "Duration",
                               "Fallback", "Valid"]
        st.dataframe(log_display, use_container_width=True, height=280)


# ── Internal helpers ──────────────────────────────────────────────────────────
def _format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    d["Result Date"] = pd.to_datetime(d["result_date"]).dt.strftime("%d %b %Y (%a)")
    d["Symbol"]      = d.get("symbol", pd.Series(["—"] * len(d), index=d.index)).fillna("—")
    d["Company"]     = d["company_name"]
    d["F&O"]         = (
        d["is_fo"].map({True: "✅ F&O", False: "—"})
        if "is_fo" in d.columns else "—"
    )

    # Sector: show only for F&O stocks with a known sector
    is_fo   = d["is_fo"].astype(bool) if "is_fo" in d.columns else pd.Series([False] * len(d), index=d.index)
    raw_sec = (
        d.get("sector", pd.Series(["—"] * len(d), index=d.index))
        .fillna("—").astype(str)
        .replace({"": "—", "nan": "—"})
    )
    d["Sector"] = raw_sec.where(is_fo, other="—")

    # Importance: text tier badge instead of progress bar
    d["Impact"] = d.apply(_importance_label, axis=1)

    d["Due In"] = d.get(
        "days_remaining",
        pd.Series([0] * len(d), index=d.index)
    ).apply(_days_label)

    # Index membership: only meaningful for F&O stocks
    d["Index"] = d.apply(
        lambda r: _index_tag_text(r) if r.get("is_fo") else "—", axis=1
    )

    return d[["Result Date", "Symbol", "Company", "F&O", "Sector", "Impact", "Due In", "Index"]]


def _importance_label(row) -> str:
    score = int(row.get("importance_score", 0) or 0)
    is_fo = bool(row.get("is_fo", False))
    if not is_fo or score == 0:
        return "—"
    if score > 60:
        return "🔴 HIGH"
    if score >= 30:
        return "🟡 MED"
    return "🟢 LOW"


def _days_label(n) -> str:
    n = int(n) if n is not None else 0
    if n == 0:  return "🔴 Today"
    if n == 1:  return "🟡 Tomorrow"
    if n <= 3:  return f"🟠 {n}d"
    return f"🟢 {n}d"


def _index_tag_text(row) -> str:
    tags = []
    if row.get("is_nifty50"):      tags.append("N50")
    if row.get("is_banknifty"):    tags.append("BNF")
    if row.get("is_nifty_next50"): tags.append("NN50")
    return " ".join(tags) if tags else "—"


def _index_badges(row) -> str:
    badges = []
    if row.get("is_nifty50"):
        badges.append(
            '<span style="background:#FFB34722;color:#FFB347;padding:1px 6px;'
            'border-radius:4px;font-size:0.65rem;margin-left:5px">N50</span>'
        )
    if row.get("is_banknifty"):
        badges.append(
            '<span style="background:#00C89622;color:#00C896;padding:1px 6px;'
            'border-radius:4px;font-size:0.65rem;margin-left:5px">BNF</span>'
        )
    if row.get("is_fo"):
        badges.append(
            '<span style="background:#00D4FF22;color:#00D4FF;padding:1px 6px;'
            'border-radius:4px;font-size:0.65rem;margin-left:5px">F&amp;O</span>'
        )
    return "".join(badges)


def _to_csv(df: pd.DataFrame) -> bytes:
    """Export with analyst-friendly column order."""
    col_order = [
        "symbol", "company_name", "result_date",
        "is_fo", "sector", "importance_score",
        "is_nifty50", "is_banknifty", "is_nifty_next50",
        "market_cap_tier", "days_remaining",
        "meeting_type", "source",
    ]
    keep = [c for c in col_order if c in df.columns]
    out  = df[keep].copy()
    if "result_date" in out.columns:
        out["result_date"] = pd.to_datetime(out["result_date"]).dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False).encode("utf-8")
