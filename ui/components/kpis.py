"""ui/components/kpis.py — KPI card rendering.

Card layout (left → right):
  1. F&O This Week   — F&O companies reporting in the next 7 days (HERO metric)
  2. Due Today        — all companies reporting today
  3. Tomorrow         — all companies reporting tomorrow
  4. Nifty 50 / BNF  — index heavyweights this week
  5. All Tracked      — total companies in window (with next-week comparison)

The previous version showed "Total" and "This Week" with the same SQL
filter so both cards always held the same inflated number (~1700+).
"""

from datetime import datetime, timedelta

import streamlit as st


def render_kpi_row(kpis: dict):
    today     = datetime.today().date()
    tomorrow  = today + timedelta(days=1)
    week_end  = today + timedelta(days=6)
    lookahead = int(kpis.get("lookahead_days", 7))

    fmt = "%d %b"

    c1, c2, c3, c4, c5 = st.columns(5)

    # Card 1 — hero metric for F&O analysts
    _card(
        c1,
        label="F&O Results This Week",
        value=kpis.get("fo_week_count", 0),
        icon="🎯",
        color="#00C896",
        sub=f"{today.strftime(fmt)} → {week_end.strftime(fmt)}  ·  "
            f"{kpis.get('fo_count', 0)} total in {lookahead}d",
    )
    # Card 2 — today's agenda
    _card(
        c2,
        label="Due Today",
        value=kpis.get("today_count", 0),
        icon="🔴",
        color="#FF6B6B",
        sub=today.strftime("%A, %d %b"),
    )
    # Card 3 — tomorrow
    _card(
        c3,
        label="Tomorrow",
        value=kpis.get("tomorrow_count", 0),
        icon="🟡",
        color="#FFB347",
        sub=tomorrow.strftime("%A, %d %b"),
    )
    # Card 4 — index heavy-hitters this week
    _card(
        c4,
        label="Nifty 50 This Week",
        value=kpis.get("nifty50_week_count", 0),
        icon="🏆",
        color="#A78BFA",
        sub=f"Bank Nifty: {kpis.get('banknifty_count', 0)}",
    )
    # Card 5 — total pipeline coverage
    week_count      = kpis.get("week_count", 0)
    next_week_count = kpis.get("next_week_count", 0)
    delta_sign      = "▲" if next_week_count > week_count else ("▼" if next_week_count < week_count else "=")
    delta_color     = "#00C896" if next_week_count >= week_count else "#FF6B6B"
    _card(
        c5,
        label="All Companies This Week",
        value=week_count,
        icon="📋",
        color="#00D4FF",
        sub=f'<span style="color:{delta_color}">{delta_sign} {next_week_count} next week</span>',
        raw_sub=True,
    )


def _card(col, label: str, value, icon: str, color: str, sub: str = "", raw_sub: bool = False):
    if sub and not raw_sub:
        sub_html = (
            f"<div style='font-size:0.68rem;color:{color};"
            f"margin-top:3px;font-family:IBM Plex Mono,monospace;"
            f"line-height:1.4'>{sub}</div>"
        )
    elif sub and raw_sub:
        sub_html = (
            f"<div style='font-size:0.68rem;margin-top:3px;"
            f"font-family:IBM Plex Mono,monospace'>{sub}</div>"
        )
    else:
        sub_html = ""

    with col:
        st.markdown(
            f"""
            <div style="
                background:#141727;
                border:1px solid #1E2340;
                border-top: 3px solid {color};
                border-radius:10px;
                padding:16px 18px 14px;
                margin-bottom:8px;
            ">
                <div style="font-size:1.4rem;margin-bottom:6px">{icon}</div>
                <div style="font-size:1.9rem;font-weight:700;
                            font-family:'IBM Plex Mono',monospace;
                            color:#E8EAF0;line-height:1">{value}</div>
                <div style="font-size:0.72rem;color:#8B8FA8;
                            text-transform:uppercase;letter-spacing:.07em;
                            margin-top:5px">{label}</div>
                {sub_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
