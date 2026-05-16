"""ui/components/kpis.py — KPI card rendering."""

import streamlit as st


def render_kpi_row(kpis: dict):
    c1, c2, c3, c4, c5 = st.columns(5)
    _card(c1, "Total Results",    kpis["total"],         "📋", "#00D4FF")
    _card(c2, "F&O Companies",    kpis["fo_count"],      "🎯", "#00C896",
          sub=f"{kpis['fo_pct']}% of total")
    _card(c3, "Nifty 50",         kpis["nifty50_count"], "🏆", "#FFB347")
    _card(c4, "Due Today",        kpis["today_count"],   "🔴", "#FF6B6B")
    _card(c5, "This Week",        kpis["week_count"],    "📅", "#A78BFA")


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
                {"<div style='font-size:0.72rem;color:" + color + ";margin-top:3px'>" + sub + "</div>" if sub else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )
