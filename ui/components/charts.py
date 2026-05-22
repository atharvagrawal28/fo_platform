"""ui/components/charts.py — Plotly chart builders.

Every public function is wrapped in a try/except so a single bad chart
never crashes the whole dashboard — it falls back to a blank placeholder.
"""

import logging

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

logger = logging.getLogger(__name__)

C = {
    "green":  "#00C896", "red": "#FF6B6B",
    "blue":   "#00D4FF", "amber": "#FFB347",
    "bg":     "rgba(0,0,0,0)", "grid": "#1E2340", "text": "#E8EAF0",
}
FONT = dict(color=C["text"], family="IBM Plex Sans, sans-serif", size=12)


def chart_daily_bar(df: pd.DataFrame) -> go.Figure:
    try:
        if df.empty:
            return _blank("No upcoming results")
        fig = px.bar(
            df, x="day_label", y=["fo_count", "non_fo_count"],
            color_discrete_map={"fo_count": C["green"], "non_fo_count": C["red"]},
            barmode="stack",
            title="Daily Results Breakdown",
            labels={"day_label": "", "value": "Results", "variable": ""},
        )
        fig.for_each_trace(lambda t: t.update(
            name="F&O" if t.name == "fo_count" else "Non-F&O",
            texttemplate="%{y}" if t.name == "Non-F&O" else "",
            textposition="outside",
        ))
        return _theme(fig)
    except Exception as e:
        logger.error("chart_daily_bar error: %s", e)
        return _blank("Chart unavailable")


def chart_sector_bar(df: pd.DataFrame) -> go.Figure:
    try:
        if df.empty:
            return _blank("No sector data")
        fig = px.bar(
            df.head(12), x="total_count", y="sector",
            orientation="h", color="fo_count",
            color_continuous_scale=[[0, "#1A1D2E"], [1, C["green"]]],
            title="Sector Concentration",
            text="total_count",
            labels={"total_count": "Results", "sector": "", "fo_count": "F&O Count"},
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
        return _theme(fig)
    except Exception as e:
        logger.error("chart_sector_bar error: %s", e)
        return _blank("Chart unavailable")


def chart_fo_donut(df: pd.DataFrame) -> go.Figure:
    try:
        if df.empty:
            return _blank("No data")
        fo     = int(df["is_fo"].astype(bool).sum()) if "is_fo" in df.columns else 0
        non_fo = len(df) - fo
        if fo == 0 and non_fo == 0:
            return _blank("No data")
        fig = go.Figure(go.Pie(
            labels=["F&O", "Non-F&O"], values=[fo, non_fo],
            hole=0.60,
            marker_colors=[C["green"], C["red"]],
        ))
        fig.update_traces(textposition="outside", textinfo="percent+label")
        fig.update_layout(title="F&O Split", showlegend=False)
        return _theme(fig)
    except Exception as e:
        logger.error("chart_fo_donut error: %s", e)
        return _blank("Chart unavailable")


def chart_importance_scatter(df: pd.DataFrame) -> go.Figure:
    try:
        if df.empty:
            return _blank("No data")
        d = df.copy()
        d["result_date"]     = pd.to_datetime(d["result_date"], errors="coerce")
        d["importance_score"] = pd.to_numeric(d["importance_score"], errors="coerce").fillna(0)
        # Only plot companies with importance > 0 — avoids Plotly errors on zero-size columns
        d = d[d["importance_score"] > 0].dropna(subset=["result_date"])
        if d.empty:
            return _blank("No ranked companies in current filter")
        fig = px.scatter(
            d, x="result_date", y="importance_score",
            hover_name="company_name",
            hover_data={"sector": True, "symbol": True, "result_date": False},
            color="sector",
            size="importance_score",
            size_max=22,
            title="Earnings Importance by Date",
            labels={"result_date": "Date", "importance_score": "Importance Score"},
        )
        return _theme(fig)
    except Exception as e:
        logger.error("chart_importance_scatter error: %s", e)
        return _blank("Chart unavailable")


# ── Internal ──────────────────────────────────────────────────────────────────
def _theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=C["bg"], plot_bgcolor=C["bg"],
        font=FONT, title_font=dict(size=14, color=C["text"]),
        margin=dict(l=8, r=8, t=44, b=8),
        legend=dict(bgcolor="rgba(20,23,39,0.85)", bordercolor=C["grid"], borderwidth=1),
        xaxis=dict(gridcolor=C["grid"], zerolinecolor=C["grid"]),
        yaxis=dict(gridcolor=C["grid"], zerolinecolor=C["grid"]),
    )
    return fig


def _blank(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(size=14, color="#8B8FA8"))
    return _theme(fig)
