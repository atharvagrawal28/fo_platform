"""ui/components/kpis.py — KPI card rendering.

Five distinct, non-overlapping cards. The previous version showed
"Total" and "This Week" with the same SQL filter, so both cards always
held the same number — making the row useless. Each card below has a
strict definition and a date-range subtitle so the meaning is obvious.
"""

from datetime import datetime, timedelta

import streamlit as st


def render_kpi_row(kpis: dict):
    today = datetime.today().date()
    week_end = today + timedelta(days=6)
    next_week_start = today + timedelta(days=7)
    next_week_end = today + timedelta(days=13)
    lookahead = int(kpis.get("lookahead_days", 7))

    fmt = "%d %b"

    c1, c2, c3, c4, c5 = st.columns(5)

    _card(
        c1,
        label="Due Today",
        value=kpis.get("today_count", 0),
        icon="🔴",
        color="#FF6B6B",
        sub=today.strftime(fmt),
    )
    _card(
        c2,
        label="Tomorrow",
        value=kpis.get("tomorrow_count", 0),
        icon="🟡",
        color="#FFB347",
        sub=(today + timedelta(days=1)).strftime(fmt),
    )
    _card(
        c3,
        label="This Week",
        value=kpis.get("week_count", 0),
        icon="📅",
        color="#00D4FF",
        sub=f"{today.strftime(fmt)} → {week_end.strftime(fmt)}",
    )
    _card(
        c4,
        label="F&O Coverage",
        value=kpis.get("fo_count", 0),
        icon="🎯",
        color="#00C896",
        sub=f"{kpis.get('fo_pct', 0)}% of {kpis.get('total', 0)} in {lookahead}d",
    )
    _card(
        c5,
        label="Nifty 50",
        value=kpis.get("nifty50_count", 0),
        icon="🏆",
        color="#A78BFA",
        sub=f"Bank Nifty: {kpis.get('banknifty_count', 0)}",
    )


def _card(col, label: str, value, icon: str, color: str, sub: str = ""):
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
                {"<div style='font-size:0.7rem;color:" + color + ";margin-top:3px;font-family:IBM Plex Mono,monospace'>" + sub + "</div>" if sub else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )
