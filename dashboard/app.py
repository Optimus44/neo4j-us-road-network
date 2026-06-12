"""
app.py — US Road Network Analytics Dashboard (Lazy Loading Version)
===================================================================
Data fetches only when a tab is clicked.
Loading spinners show during slow queries.
"""

import os
import logging

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dash import Dash, dcc, html, Input, Output
import dash_bootstrap_components as dbc
from neo4j import GraphDatabase

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "roadnetwork2024")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

COLORS = {
    "primary":    "#1565C0",
    "secondary":  "#2E7D32",
    "accent":     "#E64A19",
    "warning":    "#F57C00",
    "purple":     "#6A1B9A",
    "background": "#F8F9FA",
    "card":       "#FFFFFF",
    "text":       "#212121",
    "subtext":    "#757575",
    "border":     "#E0E0E0",
    "dark_bg":    "#0D1117",
}

# ─────────────────────────────────────────────────────────────
# DATA LAYER
# ─────────────────────────────────────────────────────────────

class RoadNetworkData:
    def __init__(self):
        self._driver = None
        self._cache  = {}

    def connect(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
            )
            self._driver.verify_connectivity()
            log.info("Connected to Neo4j")
        return self._driver

    def query(self, cypher: str, params: dict = None) -> pd.DataFrame:
        try:
            driver = self.connect()
            with driver.session() as session:
                result  = session.run(cypher, params or {})
                records = [dict(r) for r in result]
            return pd.DataFrame(records)
        except Exception as e:
            log.error(f"Query failed: {e}")
            return pd.DataFrame()

    def cached(self, key: str, cypher: str,
               params: dict = None) -> pd.DataFrame:
        if key not in self._cache:
            log.info(f"Running query: {key}")
            self._cache[key] = self.query(cypher, params)
            log.info(f"Done: {key} — {len(self._cache[key])} rows")
        return self._cache[key]

    # ── Queries — each fetches only what its tab needs ───────

    def get_summary(self) -> dict:
        df = self.cached("summary", """
            MATCH (i:Intersection)
            WITH count(i) AS nodes
            MATCH ()-[r:ROAD_TO]->()
            WITH nodes, count(r) AS roads
            RETURN nodes AS total_nodes, roads AS total_roads,
                   round(toFloat(roads * 2) / nodes, 2) AS avg_degree
        """)
        df2 = self.cached("max_degree", """
            MATCH (i:Intersection)
            WITH COUNT { (i)-[:ROAD_TO]-() } AS degree
            RETURN max(degree) AS max_degree
        """)
        if df.empty:
            return {}
        result = df.iloc[0].to_dict()
        if not df2.empty:
            result["max_degree"] = df2.iloc[0]["max_degree"]
        return result

    def get_degree_distribution(self) -> pd.DataFrame:
        return self.cached("degree_dist", """
            MATCH (i:Intersection)
            WITH COUNT { (i)-[:ROAD_TO]-() } AS degree
            RETURN degree, count(*) AS intersection_count
            ORDER BY degree ASC
        """)

    def get_categories(self) -> pd.DataFrame:
        return self.cached("categories", """
            MATCH (i:Intersection)
            WITH COUNT { (i)-[:ROAD_TO]-() } AS degree
            WITH CASE
                WHEN degree = 1 THEN 'Dead End'
                WHEN degree = 2 THEN 'Through Road'
                WHEN degree = 3 THEN 'T-Junction'
                WHEN degree = 4 THEN 'Four-Way'
                ELSE 'Complex Hub (≥5)'
            END AS category
            RETURN category, count(*) AS count
            ORDER BY count DESC
        """)

    def get_top_connected(self) -> pd.DataFrame:
        return self.cached("top_10", """
            MATCH (i:Intersection)
            WITH i, COUNT { (i)-[:ROAD_TO]-() } AS degree
            ORDER BY degree DESC LIMIT 10
            RETURN i.nodeId AS node_id, degree,
                   i.x AS x, i.y AS y
        """)

    def get_degree_stats(self) -> pd.DataFrame:
        # Uses pre-computed max_degree and degree_dist
        # to avoid a slow full-scan percentile query
        df = self.get_degree_distribution()
        if df.empty:
            return pd.DataFrame()

        # Compute statistics from the distribution DataFrame
        # This is much faster than asking Neo4j to compute percentiles
        # on 87k rows — we already have the distribution
        total     = df["intersection_count"].sum()
        deg_vals  = df["degree"].values
        deg_cnts  = df["intersection_count"].values

        mean_deg  = (deg_vals * deg_cnts).sum() / total
        min_deg   = int(deg_vals.min())
        max_deg   = int(deg_vals.max())

        # Compute percentiles from the distribution
        cumulative = 0
        p50 = p75 = p90 = p99 = None
        for d, c in zip(deg_vals, deg_cnts):
            cumulative += c
            pct = cumulative / total
            if p50 is None and pct >= 0.50:
                p50 = d
            if p75 is None and pct >= 0.75:
                p75 = d
            if p90 is None and pct >= 0.90:
                p90 = d
            if p99 is None and pct >= 0.99:
                p99 = d

        return pd.DataFrame([{
            "min_degree": min_deg,
            "max_degree": max_deg,
            "avg_degree": round(mean_deg, 4),
            "p50": p50, "p75": p75,
            "p90": p90, "p99": p99
        }])

    def get_betweenness_top(self) -> pd.DataFrame:
        return self.cached("betweenness_top", """
            MATCH (i:Intersection)
            WHERE i.betweenness IS NOT NULL
            RETURN i.nodeId AS node_id,
                   i.betweenness AS betweenness,
                   i.x AS x, i.y AS y
            ORDER BY i.betweenness DESC LIMIT 20
        """)

    def get_betweenness_sample(self) -> pd.DataFrame:
        """
        Sample 5000 random betweenness scores for the histogram.
        Sampling is intentional — we don't need all 87k points
        to show the distribution shape accurately.
        """
        return self.cached("betweenness_sample", """
            MATCH (i:Intersection)
            WHERE i.betweenness IS NOT NULL
            WITH i ORDER BY rand() LIMIT 5000
            RETURN i.betweenness AS betweenness
        """)

    def get_centrality_comparison(self) -> pd.DataFrame:
        return self.cached("centrality_compare", """
            MATCH (i:Intersection)
            WHERE i.betweenness IS NOT NULL
              AND i.pagerank    IS NOT NULL
            WITH i, COUNT { (i)-[:ROAD_TO]-() } AS degree
            RETURN i.nodeId AS node_id, degree,
                   i.betweenness AS betweenness,
                   i.pagerank    AS pagerank
            ORDER BY i.betweenness DESC LIMIT 500
        """)

    def get_spatial_sample(self) -> pd.DataFrame:
        return self.cached("spatial", """
            MATCH (i:Intersection)
            WHERE i.betweenness IS NOT NULL
            WITH i ORDER BY rand() LIMIT 6000
            RETURN i.nodeId AS node_id,
                   i.x AS x, i.y AS y,
                   i.betweenness AS betweenness,
                   COUNT { (i)-[:ROAD_TO]-() } AS degree
        """)


data = RoadNetworkData()


# ─────────────────────────────────────────────────────────────
# CHART BUILDERS
# ─────────────────────────────────────────────────────────────

def empty_chart(message: str, height: int = 350) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=13, color=COLORS["subtext"]),
        align="center"
    )
    fig.update_layout(
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["card"],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(t=40, b=40, l=40, r=40),
        height=height
    )
    return fig


def build_degree_dist(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_chart("No degree data available")
    mean_deg = (
        (df["degree"] * df["intersection_count"]).sum()
        / df["intersection_count"].sum()
    )
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["degree"], y=df["intersection_count"],
        marker_color=COLORS["primary"],
        marker_line_color="white", marker_line_width=0.5,
        hovertemplate=(
            "<b>Degree %{x}</b><br>"
            "Intersections: %{y:,}<extra></extra>"
        )
    ))
    fig.add_vline(
        x=mean_deg, line_dash="dash",
        line_color=COLORS["accent"],
        annotation_text=f"Mean: {mean_deg:.2f}",
        annotation_font_color=COLORS["accent"],
        annotation_position="top right"
    )
    fig.update_layout(
        title="Degree Distribution",
        xaxis_title="Degree (Number of Roads)",
        yaxis_title="Number of Intersections",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["card"],
        xaxis=dict(dtick=1, gridcolor=COLORS["border"]),
        yaxis=dict(gridcolor=COLORS["border"], tickformat=","),
        margin=dict(t=50, b=50, l=70, r=30),
        showlegend=False, height=400
    )
    return fig


def build_categories(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_chart("No category data available")
    palette = [
        COLORS["secondary"], COLORS["primary"],
        COLORS["warning"],   COLORS["accent"],
        COLORS["purple"]
    ]
    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "pie"}, {"type": "bar"}]],
        subplot_titles=["Proportion", "Count"]
    )
    fig.add_trace(go.Pie(
        labels=df["category"], values=df["count"],
        marker_colors=palette[:len(df)],
        hovertemplate=(
            "<b>%{label}</b><br>"
            "Count: %{value:,}<br>"
            "Share: %{percent}<extra></extra>"
        ),
        textinfo="percent", showlegend=True
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=df["category"], y=df["count"],
        marker_color=palette[:len(df)],
        hovertemplate=(
            "<b>%{x}</b><br>Count: %{y:,}<extra></extra>"
        ),
        showlegend=False
    ), row=1, col=2)
    fig.update_layout(
        title="Intersection Categories by Connectivity",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["card"],
        margin=dict(t=60, b=50, l=50, r=30), height=400
    )
    fig.update_yaxes(
        gridcolor=COLORS["border"], tickformat=",", row=1, col=2
    )
    return fig


def build_top_connected(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_chart("No data available")
    df = df.sort_values("degree", ascending=True)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["degree"],
        y=df["node_id"].astype(str).apply(lambda x: f"Node {x}"),
        orientation="h",
        marker=dict(
            color=df["degree"], colorscale="Blues",
            showscale=True,
            colorbar=dict(title="Degree", thickness=12)
        ),
        hovertemplate=(
            "<b>Node %{customdata}</b><br>"
            "Degree: %{x}<extra></extra>"
        ),
        customdata=df["node_id"]
    ))
    fig.update_layout(
        title="Top 10 Most Connected Intersections",
        xaxis_title="Degree",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["card"],
        xaxis=dict(gridcolor=COLORS["border"]),
        yaxis=dict(gridcolor=COLORS["border"]),
        margin=dict(t=50, b=50, l=120, r=30),
        showlegend=False, height=400
    )
    return fig


def build_betweenness_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_chart(
            "No betweenness data found.\n"
            "Run in Neo4j Browser:\n"
            "CALL gds.betweenness.write('roadNetwork',\n"
            "{writeProperty: 'betweenness', samplingSize: 100})"
        )
    df = df.sort_values("betweenness", ascending=True)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["betweenness"],
        y=df["node_id"].astype(str).apply(lambda x: f"Node {x}"),
        orientation="h",
        marker=dict(
            color=df["betweenness"], colorscale="Purples",
            showscale=True,
            colorbar=dict(title="Score", thickness=12)
        ),
        hovertemplate=(
            "<b>Node %{customdata}</b><br>"
            "Betweenness: %{x:,.2f}<extra></extra>"
        ),
        customdata=df["node_id"]
    ))
    fig.update_layout(
        title="Top 20 Intersections by Betweenness Centrality",
        xaxis_title="Betweenness Score",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["card"],
        xaxis=dict(gridcolor=COLORS["border"]),
        yaxis=dict(gridcolor=COLORS["border"]),
        margin=dict(t=50, b=50, l=120, r=30),
        showlegend=False, height=520
    )
    return fig


def build_betweenness_hist(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_chart("Betweenness scores not computed")
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=df["betweenness"], nbinsx=60,
        marker_color=COLORS["purple"],
        marker_line_color="white", marker_line_width=0.3,
        hovertemplate=(
            "Score: %{x:.0f}<br>Count: %{y:,}<extra></extra>"
        )
    ))
    fig.update_layout(
        title="Betweenness Centrality Distribution (log scale)",
        xaxis_title="Betweenness Score",
        yaxis_title="Intersections (log scale)",
        yaxis_type="log",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["card"],
        xaxis=dict(gridcolor=COLORS["border"]),
        yaxis=dict(gridcolor=COLORS["border"]),
        margin=dict(t=50, b=50, l=70, r=30),
        showlegend=False, height=380
    )
    return fig


def build_centrality_scatter(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_chart(
            "PageRank not yet computed.\n"
            "Run in Neo4j Browser:\n"
            "CALL gds.pageRank.write('roadNetwork',\n"
            "{writeProperty: 'pagerank', maxIterations: 20})"
        )
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["betweenness"], y=df["pagerank"],
        mode="markers",
        marker=dict(
            size=5, color=df["degree"],
            colorscale="Viridis", showscale=True,
            colorbar=dict(title="Degree", thickness=12),
            opacity=0.75
        ),
        hovertemplate=(
            "<b>Node %{customdata}</b><br>"
            "Betweenness: %{x:,.1f}<br>"
            "PageRank: %{y:.6f}<extra></extra>"
        ),
        customdata=df["node_id"]
    ))
    fig.update_layout(
        title="Betweenness vs PageRank — Top 500 by Betweenness",
        xaxis_title="Betweenness Centrality",
        yaxis_title="PageRank Score",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["card"],
        xaxis=dict(gridcolor=COLORS["border"]),
        yaxis=dict(gridcolor=COLORS["border"]),
        margin=dict(t=50, b=50, l=70, r=30), height=420
    )
    return fig


def build_spatial_map(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return empty_chart(
            "Betweenness scores required for spatial map",
            height=580
        )
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["x"], y=df["y"],
        mode="markers",
        marker=dict(
            size=2.5, color=df["betweenness"],
            colorscale="Hot", showscale=True,
            colorbar=dict(title="Betweenness", thickness=12),
            opacity=0.85
        ),
        hovertemplate=(
            "<b>Node %{customdata[0]}</b><br>"
            "Location: (%{x}, %{y})<br>"
            "Betweenness: %{marker.color:,.1f}<br>"
            "Degree: %{customdata[1]}<extra></extra>"
        ),
        customdata=df[["node_id", "degree"]].values
    ))
    fig.update_layout(
        title="Spatial Map — Intersection Betweenness Centrality",
        xaxis_title="X Coordinate",
        yaxis_title="Y Coordinate",
        plot_bgcolor=COLORS["dark_bg"],
        paper_bgcolor=COLORS["card"],
        xaxis=dict(gridcolor="#2d2d4e", showgrid=True),
        yaxis=dict(
            gridcolor="#2d2d4e", showgrid=True,
            scaleanchor="x", scaleratio=1
        ),
        margin=dict(t=50, b=50, l=70, r=30), height=600
    )
    return fig


# ─────────────────────────────────────────────────────────────
# LAYOUT HELPERS
# ─────────────────────────────────────────────────────────────

def kpi_card(title, value, subtitle="", color=COLORS["primary"]):
    return dbc.Card(dbc.CardBody([
        html.P(title, style={
            "color": COLORS["subtext"], "fontSize": "0.8rem",
            "fontWeight": "600", "textTransform": "uppercase",
            "letterSpacing": "0.5px", "marginBottom": "4px"
        }),
        html.H3(value, style={
            "color": color, "fontWeight": "700",
            "marginBottom": "4px"
        }),
        html.P(subtitle, style={
            "color": COLORS["subtext"],
            "fontSize": "0.78rem", "margin": "0"
        })
    ]), style={
        "border":          f"1px solid {COLORS['border']}",
        "borderRadius":    "10px",
        "boxShadow":       "0 2px 8px rgba(0,0,0,0.06)",
        "backgroundColor": COLORS["card"]
    })


def stats_table(df: pd.DataFrame):
    if df.empty:
        return html.P("No data",
                      style={"color": COLORS["subtext"]})
    row = df.iloc[0]
    rows = [
        ("Minimum degree",  f"{int(row['min_degree'])}"),
        ("Maximum degree",  f"{int(row['max_degree'])}"),
        ("Average degree",  f"{row['avg_degree']:.4f}"),
        ("Median (p50)",    f"{row['p50']}"),
        ("75th percentile", f"{row['p75']}"),
        ("90th percentile", f"{row['p90']}"),
        ("99th percentile", f"{row['p99']}"),
    ]
    return dbc.Table(
        [html.Thead(html.Tr([
            html.Th("Statistic",
                    style={"backgroundColor": COLORS["background"]}),
            html.Th("Value",
                    style={"backgroundColor": COLORS["background"]})
        ]))] +
        [html.Tbody([
            html.Tr([html.Td(label), html.Td(val)])
            for label, val in rows
        ])],
        bordered=True, hover=True, responsive=True,
        style={"fontSize": "0.9rem", "marginTop": "12px"}
    )


# ─────────────────────────────────────────────────────────────
# APP INITIALIZATION
# ─────────────────────────────────────────────────────────────

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    title="Road Network Analytics"
)

# ─────────────────────────────────────────────────────────────
# TAB STYLES
# ─────────────────────────────────────────────────────────────

TAB_STYLE = {
    "padding":           "10px 24px",
    "fontWeight":        "500",
    "fontSize":          "0.95rem",
    "color":             COLORS["subtext"],
    "backgroundColor":   COLORS["background"],
    "border":            f"1px solid {COLORS['border']}",
    "borderBottom":      "none",
    "borderRadius":      "6px 6px 0 0",
}
TAB_SELECTED = {
    "padding":           "10px 24px",
    "fontWeight":        "700",
    "fontSize":          "0.95rem",
    "color":             COLORS["primary"],
    "backgroundColor":   COLORS["card"],
    "border":            f"1px solid {COLORS['border']}",
    "borderBottom":      f"2px solid {COLORS['primary']}",
    "borderRadius":      "6px 6px 0 0",
}

# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────

app.layout = dbc.Container([

    # ── Header ───────────────────────────────────────────────
    dbc.Row(dbc.Col(html.Div([
        html.H1(
            "US Road Network Analytics",
            style={"color":      COLORS["primary"],
                   "fontWeight": "700",
                   "marginBottom": "4px"}
        ),
        html.P(
            "Graph analysis of 87,575 intersections and 121,491 roads "
            "· Powered by Neo4j Graph Data Science",
            style={"color": COLORS["subtext"], "fontSize": "1rem"}
        )
    ])), className="mt-4 mb-4"),

    # ── KPI Row ───────────────────────────────────────────────
    dbc.Row([
        dbc.Col(html.Div(id="kpi-1"), md=3),
        dbc.Col(html.Div(id="kpi-2"), md=3),
        dbc.Col(html.Div(id="kpi-3"), md=3),
        dbc.Col(html.Div(id="kpi-4"), md=3),
    ], className="mb-4 g-3"),

    # ── Tabs ──────────────────────────────────────────────────
    dcc.Tabs(
        id="main-tabs",
        value="tab-overview",
        children=[
            dcc.Tab(label="Overview",
                    value="tab-overview",
                    style=TAB_STYLE,
                    selected_style=TAB_SELECTED),
            dcc.Tab(label="Degree Analysis",
                    value="tab-degree",
                    style=TAB_STYLE,
                    selected_style=TAB_SELECTED),
            dcc.Tab(label="Centrality",
                    value="tab-centrality",
                    style=TAB_STYLE,
                    selected_style=TAB_SELECTED),
            dcc.Tab(label="Spatial Map",
                    value="tab-spatial",
                    style=TAB_STYLE,
                    selected_style=TAB_SELECTED),
        ]
    ),

    # Tab content — wrapped in Loading for spinner
    dcc.Loading(
        id="loading-tab",
        type="circle",
        color=COLORS["primary"],
        children=html.Div(
            id="tab-content",
            style={
                "backgroundColor": COLORS["card"],
                "border":          f"1px solid {COLORS['border']}",
                "borderTop":       "none",
                "borderRadius":    "0 0 8px 8px",
                "padding":         "24px",
                "marginBottom":    "24px",
                "minHeight":       "420px"
            }
        )
    ),

    # ── Footer ────────────────────────────────────────────────
    html.Hr(style={"borderColor": COLORS["border"]}),
    html.P(
        "Neo4j 5.26 · GDS 2.13 · Plotly Dash · "
        "US Road Network Graph Analysis",
        style={"color":     COLORS["subtext"],
               "fontSize":  "0.8rem",
               "textAlign": "center",
               "marginBottom": "16px"}
    )

], fluid=True, style={
    "backgroundColor": COLORS["background"],
    "minHeight":       "100vh",
    "fontFamily":      "Arial, sans-serif"
})


# ─────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────

@app.callback(
    Output("kpi-1", "children"),
    Output("kpi-2", "children"),
    Output("kpi-3", "children"),
    Output("kpi-4", "children"),
    Input("main-tabs", "value")
)
def update_kpis(_):
    """KPIs load once and are cached."""
    s = data.get_summary()
    if not s:
        err = kpi_card("Error", "N/A", "Cannot connect to Neo4j")
        return err, err, err, err
    return (
        kpi_card("Total Intersections",
                 f"{int(s.get('total_nodes', 0)):,}",
                 "nodes in graph",
                 COLORS["primary"]),
        kpi_card("Total Roads",
                 f"{int(s.get('total_roads', 0)):,}",
                 "relationships",
                 COLORS["secondary"]),
        kpi_card("Average Degree",
                 f"{s.get('avg_degree', 0):.2f}",
                 "roads per intersection",
                 COLORS["warning"]),
        kpi_card("Maximum Degree",
                 f"{int(s.get('max_degree', 0))}",
                 "most connected node",
                 COLORS["accent"]),
    )


@app.callback(
    Output("tab-content", "children"),
    Input("main-tabs", "value")
)
def render_tab(tab: str):
    """
    Render tab content on demand.
    Each branch fetches only the data that tab needs.
    Results are cached — switching back to a tab is instant.
    """

    if tab == "tab-overview":
        return dbc.Row([
            dbc.Col(
                dcc.Graph(
                    figure=build_degree_dist(
                        data.get_degree_distribution()
                    ),
                    config={"displayModeBar": False}
                ), md=7
            ),
            dbc.Col(
                dcc.Graph(
                    figure=build_categories(
                        data.get_categories()
                    ),
                    config={"displayModeBar": False}
                ), md=5
            ),
        ], className="g-3")

    elif tab == "tab-degree":
        return dbc.Row([
            dbc.Col(
                dcc.Graph(
                    figure=build_top_connected(
                        data.get_top_connected()
                    ),
                    config={"displayModeBar": False}
                ), md=7
            ),
            dbc.Col([
                html.H5("Degree Statistics",
                        style={"color":      COLORS["text"],
                               "fontWeight": "600",
                               "marginTop":  "12px"}),
                stats_table(data.get_degree_stats())
            ], md=5),
        ], className="g-3")

    elif tab == "tab-centrality":
        return html.Div([
            dbc.Row([
                dbc.Col(
                    dcc.Graph(
                        figure=build_betweenness_bar(
                            data.get_betweenness_top()
                        ),
                        config={"displayModeBar": False}
                    ), md=6
                ),
                dbc.Col(
                    dcc.Graph(
                        figure=build_betweenness_hist(
                            data.get_betweenness_sample()
                        ),
                        config={"displayModeBar": False}
                    ), md=6
                ),
            ], className="g-3"),
            dbc.Row([
                dbc.Col(
                    dcc.Graph(
                        figure=build_centrality_scatter(
                            data.get_centrality_comparison()
                        ),
                        config={"displayModeBar": False}
                    ), md=12
                ),
            ], className="mt-3")
        ])

    elif tab == "tab-spatial":
        return dcc.Graph(
            figure=build_spatial_map(data.get_spatial_sample()),
            config={"displayModeBar": True},
            style={"height": "620px"}
        )

    return html.P("Select a tab.", style={"color": COLORS["subtext"]})


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=True)