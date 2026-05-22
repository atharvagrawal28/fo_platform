"""ui/components/charts.py — Plotly chart builders."""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

C = {
    "green":  "#00C896", "red": "#FF6B6B",
    "blue":   "#00D4FF", "amber": "#FFB347",
    "bg":     "rgba(0,0,0,0)", "grid": "#1E2340", "text": "#E8EAF0",
}
FONT = dict(color=C["text"], family="IBM Plex Sans, sans-serif", size=12)


def chart_daily_bar(df: pd.DataFrame) -> go.Figure:
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
        # Show total on the top of each stacked bar only — avoids overlapping
        # labels on small segments when one category is near zero.
        texttemplate="%{y}" if t.name == "Non-F&O" else "",
        textposition="outside",
    ))
    return _theme(fig)


def chart_sector_bar(df: pd.DataFrame) -> go.Figure:
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


def chart_fo_donut(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _blank("No data")
    fo     = int(df["is_fo"].sum()) if "is_fo" in df.columns else 0
    non_fo = len(df) - fo
    fig = go.Figure(go.Pie(
        labels=["F&O", "Non-F&O"], values=[fo, non_fo],
        hole=0.60,
        marker_colors=[C["green"], C["red"]],
    ))
    fig.update_traces(textposition="outside", textinfo="percent+label")
    fig.update_layout(title="F&O Split", showlegend=False)
    return _theme(fig)


def chart_importance_scatter(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _blank("No data")
    d = df.copy()
    d["result_date"] = pd.to_datetime(d["result_date"])
    # Only plot companies with importance > 0; others are untracked SME noise.
    # Also avoids Plotly ValueError when size column is all-zero.
    d = d[d["importance_score"] > 0]
    if d.empty:
        return _blank("No ranked companies in current filter")
    fig = px.scatter(
        d, x="result_date", y="importance_score",
        hover_name="company_name",
        hover_data={"sector": True, "symbol": True, "result_date": False},
        color="sector",
        size="importance_score",
        size_max=22,
        size_min=6,            # prevents invisible zero-sized dots
        title="Earnings Importance by Date",
        labels={"result_date": "Date", "importance_score": "Importance Score"},
    )
    return _theme(fig)


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
