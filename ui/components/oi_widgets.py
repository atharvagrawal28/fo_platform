"""
ui/components/oi_widgets.py
---------------------------
Rendering functions for the OI Positioning Intelligence tab.

Visual design principles:
  - Institutional style: dense signal, minimal clutter
  - Color semantics: green=bullish, red=bearish, amber=covering, grey=unwinding
  - Every widget degrades gracefully (no crashes on missing data)
  - No buy/sell language; observational framing only
"""

import logging

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pipeline.classify_buildup import BUILDUP_META

logger = logging.getLogger(__name__)

_BG    = "rgba(0,0,0,0)"
_GRID  = "#1E2340"
_TEXT  = "#E8EAF0"
_MUTED = "#8B8FA8"
_FONT  = dict(color=_TEXT, family="IBM Plex Sans, sans-serif", size=12)


# ── Summary Cards ─────────────────────────────────────────────────────────────
def render_buildup_cards(summary: dict):
    """Five KPI cards: one per buildup type + strong-signals count."""
    snap_date = summary.get("snapshot_date", "")
    if snap_date:
        try:
            snap_label = pd.to_datetime(snap_date).strftime("%d %b %Y")
        except Exception:
            snap_label = str(snap_date)
    else:
        snap_label = "—"

    st.markdown(
        f'<div style="font-size:0.7rem;color:{_MUTED};margin-bottom:8px">'
        f'Snapshot: <b style="color:{_TEXT}">{snap_label}</b> &nbsp;·&nbsp; '
        f'F&O universe tracked: <b style="color:{_TEXT}">{summary.get("total", 0)}</b>'
        f'</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    _buildup_card(c1, "Long Buildup",   summary.get("long_buildup",   0),
                  BUILDUP_META["Long Buildup"]["color"],   "🟢",
                  "Bulls adding positions")
    _buildup_card(c2, "Short Buildup",  summary.get("short_buildup",  0),
                  BUILDUP_META["Short Buildup"]["color"],  "🔴",
                  "Bears adding positions")
    _buildup_card(c3, "Short Covering", summary.get("short_covering", 0),
                  BUILDUP_META["Short Covering"]["color"], "🟡",
                  "Shorts exiting / buying back")
    _buildup_card(c4, "Long Unwinding", summary.get("long_unwinding", 0),
                  BUILDUP_META["Long Unwinding"]["color"], "⚫",
                  "Longs exiting / selling")
    _buildup_card(c5, "Strong Signals", summary.get("strong_signals", 0),
                  "#00D4FF", "⚡",
                  f"Pre-earnings: {summary.get('earnings_week_count', 0)} stocks")


def _buildup_card(col, label: str, value: int, color: str, icon: str, sub: str):
    with col:
        st.markdown(
            f"""
            <div style="background:#141727;border:1px solid #1E2340;
                        border-top:3px solid {color};border-radius:10px;
                        padding:14px 16px 12px;margin-bottom:8px">
                <div style="font-size:1.3rem;margin-bottom:4px">{icon}</div>
                <div style="font-size:1.9rem;font-weight:700;
                            font-family:'IBM Plex Mono',monospace;
                            color:#E8EAF0;line-height:1">{value}</div>
                <div style="font-size:0.7rem;color:#8B8FA8;text-transform:uppercase;
                            letter-spacing:.07em;margin-top:5px">{label}</div>
                <div style="font-size:0.65rem;color:{color};margin-top:3px">{sub}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Quadrant Scatter (signature chart) ───────────────────────────────────────
def chart_oi_quadrant(df: pd.DataFrame) -> go.Figure:
    """
    Price change % (X) vs OI change % (Y) scatter.
    Quadrant labels show buildup classification zones.
    Points colored by buildup type, sized by open interest.
    """
    try:
        if df.empty:
            return _blank("No OI data available")

        d = df[df["buildup_type"] != "Neutral"].copy()
        if d.empty:
            d = df.copy()  # show all if none classified

        color_map = {k: v["color"] for k, v in BUILDUP_META.items()}

        # Size by OI (log-scaled to prevent tiny/giant dots)
        d["_oi_size"] = d["open_interest"].clip(lower=1)

        # Hover text
        d["_hover"] = d.apply(
            lambda r: (
                f"<b>{r.get('company_name', r['symbol'])}</b><br>"
                f"Symbol: {r['symbol']}<br>"
                f"Sector: {r.get('sector', '—')}<br>"
                f"Price Δ: {r['price_chg_pct']:+.2f}%<br>"
                f"OI Δ: {r['oi_chg_pct']:+.2f}%<br>"
                f"OI: {int(r['open_interest']):,}<br>"
                f"Classification: <b>{r['buildup_type']}</b><br>"
                + (f"<br>⚠ Earnings in {int(r['days_to_earnings'])}d"
                   if r.get("has_earnings_this_week") else "")
            ),
            axis=1,
        )

        fig = go.Figure()

        for btype, meta in BUILDUP_META.items():
            sub = d[d["buildup_type"] == btype]
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub["price_chg_pct"],
                y=sub["oi_chg_pct"],
                mode="markers",
                name=btype,
                marker=dict(
                    color=meta["color"],
                    size=(sub["_oi_size"].apply(
                        lambda v: max(6, min(24, int(v ** 0.25)))
                    )).tolist(),
                    line=dict(color="#0D0F1C", width=0.5),
                    opacity=0.85,
                ),
                text=sub["_hover"],
                hovertemplate="%{text}<extra></extra>",
                customdata=sub[["symbol"]].values,
            ))

        # Quadrant lines
        for v in [0]:
            fig.add_hline(y=v, line_color=_GRID, line_width=1)
            fig.add_vline(x=v, line_color=_GRID, line_width=1)

        # Quadrant labels
        x_max = max(abs(d["price_chg_pct"].max()), abs(d["price_chg_pct"].min()), 1) * 0.8
        y_max = max(abs(d["oi_chg_pct"].max()), abs(d["oi_chg_pct"].min()), 1) * 0.8

        for text, x, y, color in [
            ("Long Buildup",   x_max,  y_max,  BUILDUP_META["Long Buildup"]["color"]),
            ("Short Buildup",  -x_max, y_max,  BUILDUP_META["Short Buildup"]["color"]),
            ("Short Covering", x_max,  -y_max, BUILDUP_META["Short Covering"]["color"]),
            ("Long Unwinding", -x_max, -y_max, BUILDUP_META["Long Unwinding"]["color"]),
        ]:
            fig.add_annotation(
                x=x, y=y, text=text,
                showarrow=False,
                font=dict(size=9, color=color),
                opacity=0.5,
            )

        fig.update_layout(
            title="Positioning Quadrant — Price Δ% vs OI Δ%",
            xaxis_title="Price Change %",
            yaxis_title="OI Change %",
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            font=_FONT, title_font=dict(size=13, color=_TEXT),
            margin=dict(l=8, r=8, t=44, b=8),
            legend=dict(bgcolor="rgba(20,23,39,0.85)",
                        bordercolor=_GRID, borderwidth=1,
                        font=dict(size=10)),
            xaxis=dict(gridcolor=_GRID, zerolinecolor="#2A2D40",
                       zerolinewidth=2, tickformat="+.1f"),
            yaxis=dict(gridcolor=_GRID, zerolinecolor="#2A2D40",
                       zerolinewidth=2, tickformat="+.1f"),
        )
        return fig

    except Exception as e:
        logger.error("chart_oi_quadrant error: %s", e)
        return _blank("Chart unavailable")


# ── Sector Heatmap ────────────────────────────────────────────────────────────
def chart_sector_heatmap(sector_df: pd.DataFrame) -> go.Figure:
    """Sector × buildup-type heatmap showing distribution of positioning activity."""
    try:
        if sector_df.empty:
            return _blank("No sector buildup data")

        btypes = ["Long Buildup", "Short Buildup", "Short Covering", "Long Unwinding"]
        colors = [BUILDUP_META[b]["color"] for b in btypes]

        sectors = sector_df["sector"].tolist()
        x_labels = [b.replace(" ", "\n") for b in btypes]

        fig = go.Figure()
        for i, (btype, color) in enumerate(zip(btypes, colors)):
            vals = sector_df.get(btype, pd.Series([0] * len(sectors))).tolist()
            fig.add_trace(go.Bar(
                name=btype,
                x=vals,
                y=sectors,
                orientation="h",
                marker_color=color,
                marker_opacity=0.8,
                hovertemplate=f"<b>%{{y}}</b><br>{btype}: %{{x}}<extra></extra>",
            ))

        fig.update_layout(
            barmode="stack",
            title="Sector Positioning Distribution",
            paper_bgcolor=_BG, plot_bgcolor=_BG,
            font=_FONT, title_font=dict(size=13, color=_TEXT),
            margin=dict(l=8, r=8, t=44, b=8),
            legend=dict(bgcolor="rgba(20,23,39,0.85)",
                        bordercolor=_GRID, borderwidth=1,
                        orientation="h", y=-0.15),
            xaxis=dict(gridcolor=_GRID, title="Count"),
            yaxis=dict(gridcolor=_GRID, autorange="reversed"),
        )
        return fig

    except Exception as e:
        logger.error("chart_sector_heatmap error: %s", e)
        return _blank("Chart unavailable")


# ── Pre-Earnings Positioning Panel ───────────────────────────────────────────
def render_earnings_oi_panel(df: pd.DataFrame):
    """
    Stocks reporting results this week + their current derivatives positioning.
    This is the EVENT + POSITIONING intelligence core view.
    """
    if df.empty:
        st.info(
            "No F&O stocks with upcoming results found in the current window. "
            "This panel populates when earnings season is active.",
            icon="ℹ️",
        )
        return

    for _, row in df.iterrows():
        btype   = row.get("buildup_type", "Neutral")
        meta    = BUILDUP_META.get(btype, BUILDUP_META["Neutral"])
        color   = meta["color"]
        icon    = meta["icon"]
        days    = int(row.get("days_to_earnings", 0) or 0)
        due_txt = "Today" if days == 0 else f"in {days}d"
        n50     = "🏆" if row.get("is_nifty50") else ""
        bnf     = "🏦" if row.get("is_banknifty") else ""
        name    = row.get("company_name") or row.get("symbol", "")
        p_chg   = float(row.get("price_chg_pct", 0) or 0)
        oi_chg  = float(row.get("oi_chg_pct", 0) or 0)
        sector  = row.get("sector", "") or "—"
        strength = row.get("buildup_strength", "") or ""

        p_color = "#00C896" if p_chg >= 0 else "#FF6B6B"
        o_color = "#00C896" if oi_chg > 0 else "#FF6B6B"

        strength_badge = ""
        if strength == "Strong":
            strength_badge = (
                '<span style="background:#00D4FF22;color:#00D4FF;'
                'padding:1px 6px;border-radius:4px;font-size:0.6rem;'
                'margin-left:6px">STRONG</span>'
            )

        st.markdown(
            f"""
            <div style="background:#141727;border:1px solid #1E2340;
                        border-left:3px solid {color};border-radius:8px;
                        padding:10px 14px;margin-bottom:8px;
                        display:flex;justify-content:space-between;align-items:center">
                <div>
                    <span style="font-size:0.88rem;font-weight:600;color:#E8EAF0">
                        {n50}{bnf} {name}
                    </span>
                    <span style="font-size:0.7rem;color:#8B8FA8;margin-left:8px">
                        {row.get('symbol','')} · {sector}
                    </span>
                    <br>
                    <span style="background:{color}22;color:{color};
                                 padding:1px 8px;border-radius:4px;
                                 font-size:0.7rem;font-weight:600;margin-top:4px;
                                 display:inline-block">
                        {icon} {btype}
                    </span>{strength_badge}
                </div>
                <div style="text-align:right;min-width:140px">
                    <div style="font-size:0.72rem;color:#8B8FA8">
                        Results <b style="color:#FFB347">{due_txt}</b>
                    </div>
                    <div style="font-size:0.7rem;margin-top:4px">
                        <span style="color:{p_color}">Price {p_chg:+.2f}%</span>
                        &nbsp;·&nbsp;
                        <span style="color:{o_color}">OI {oi_chg:+.2f}%</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Strongest Signals Table ───────────────────────────────────────────────────
def render_strongest_signals(df: pd.DataFrame):
    """Compact table of top positioning shifts by OI change magnitude."""
    if df.empty:
        st.info("No significant positioning shifts detected today.", icon="ℹ️")
        return

    display = pd.DataFrame()
    display["Symbol"]    = df["symbol"]
    display["Company"]   = df.get("company_name", df["symbol"])
    display["Sector"]    = df.get("sector", "—").fillna("—")
    display["Type"]      = df["buildup_type"]
    display["Strength"]  = df.get("buildup_strength", "").fillna("")
    display["Price Δ%"]  = df["price_chg_pct"].round(2)
    display["OI Δ%"]     = df["oi_chg_pct"].round(2)
    display["OI"]        = df["open_interest"].astype(int)
    display["Vol"]       = df["volume_contracts"].astype(int)
    display["Earnings?"] = df.get("has_earnings_this_week", False).map(
        {True: "⚠ Yes", False: ""}
    )

    st.dataframe(
        display,
        use_container_width=True,
        height=420,
        column_config={
            "Symbol":   st.column_config.TextColumn(width="small"),
            "Company":  st.column_config.TextColumn(width="large"),
            "Sector":   st.column_config.TextColumn(width="medium"),
            "Type":     st.column_config.TextColumn(width="medium"),
            "Strength": st.column_config.TextColumn(width="small"),
            "Price Δ%": st.column_config.NumberColumn(format="%.2f", width="small"),
            "OI Δ%":    st.column_config.NumberColumn(format="%.2f", width="small"),
            "OI":       st.column_config.NumberColumn(format="%d",    width="small"),
            "Vol":      st.column_config.NumberColumn(format="%d",    width="small"),
            "Earnings?":st.column_config.TextColumn(width="small"),
        },
    )


# ── Internal ──────────────────────────────────────────────────────────────────
def _theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=_FONT, margin=dict(l=8, r=8, t=44, b=8),
        xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
        yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
    )
    return fig


def _blank(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg, xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=14, color=_MUTED),
    )
    return _theme(fig)
