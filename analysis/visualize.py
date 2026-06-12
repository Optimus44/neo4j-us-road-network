"""
visualize.py — US Road Network Visualization Suite
===================================================
Generates all required charts for the project.
Saves PNG files to analysis/output/ directory.
Also displays charts interactively when run directly.

Requirements:
    pip install neo4j pandas plotly kaleido
"""

import os
import sys
import logging
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express       as px
from plotly.subplots        import make_subplots
from neo4j                  import GraphDatabase

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "roadnetwork2024")
OUTPUT_DIR     = Path("analysis/output")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# NEO4J CONNECTION
# ─────────────────────────────────────────────────────────────

def get_driver():
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    driver.verify_connectivity()
    return driver


def query_to_df(driver, cypher: str, params: dict = None) -> pd.DataFrame:
    """Execute a Cypher query and return results as a DataFrame."""
    with driver.session() as session:
        result = session.run(cypher, params or {})
        records = [dict(record) for record in result]
    return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────
# DATA FETCHING — pull all required data from Neo4j
# ─────────────────────────────────────────────────────────────

def fetch_summary_stats(driver) -> dict:
    """Fetch top-level network statistics."""
    df = query_to_df(driver, """
        MATCH (i:Intersection)
        WITH count(i) AS total_nodes
        MATCH ()-[r:ROAD_TO]->()
        WITH total_nodes, count(r) AS total_roads
        RETURN
            total_nodes,
            total_roads,
            round(toFloat(total_roads * 2) / total_nodes, 3)
                AS avg_degree
    """)
    return df.iloc[0].to_dict()


def fetch_degree_distribution(driver) -> pd.DataFrame:
    """Fetch the full degree distribution."""
    return query_to_df(driver, """
        MATCH (i:Intersection)
        WITH COUNT { (i)-[:ROAD_TO]-() } AS degree
        RETURN
            degree,
            count(*) AS intersection_count
        ORDER BY degree ASC
    """)


def fetch_top_connected(driver, limit: int = 10) -> pd.DataFrame:
    """Fetch the top N most connected intersections."""
    return query_to_df(driver, """
        MATCH (i:Intersection)
        WITH i, COUNT { (i)-[:ROAD_TO]-() } AS degree
        ORDER BY degree DESC
        LIMIT $limit
        RETURN
            'Node ' + toString(i.nodeId)   AS intersection_label,
            i.nodeId                        AS node_id,
            degree,
            i.x                             AS x,
            i.y                             AS y
    """, {"limit": limit})


def fetch_betweenness_distribution(driver) -> pd.DataFrame:
    """Fetch betweenness centrality scores for all nodes."""
    return query_to_df(driver, """
        MATCH (i:Intersection)
        WHERE i.betweenness IS NOT NULL
        RETURN i.betweenness AS betweenness
        ORDER BY betweenness DESC
    """)


def fetch_centrality_comparison(driver, limit: int = 500) -> pd.DataFrame:
    """
    Fetch degree, betweenness, and pagerank for comparison.
    Limited to top N by betweenness for readable scatter plot.
    """
    return query_to_df(driver, """
        MATCH (i:Intersection)
        WHERE i.betweenness IS NOT NULL
          AND i.pagerank    IS NOT NULL
        WITH i, COUNT { (i)-[:ROAD_TO]-() } AS degree
        RETURN
            i.nodeId                AS node_id,
            degree,
            i.betweenness           AS betweenness,
            i.pagerank              AS pagerank,
            i.closeness             AS closeness
        ORDER BY i.betweenness DESC
        LIMIT $limit
    """, {"limit": limit})


def fetch_connectivity_categories(driver) -> pd.DataFrame:
    """
    Categorize intersections by degree into connectivity tiers.
    Returns count per category.
    """
    return query_to_df(driver, """
        MATCH (i:Intersection)
        WITH i, COUNT { (i)-[:ROAD_TO]-() } AS degree
        WITH
            CASE
                WHEN degree = 1 THEN '1 - Dead End (degree=1)'
                WHEN degree = 2 THEN '2 - Through Road (degree=2)'
                WHEN degree = 3 THEN '3 - T-Junction (degree=3)'
                WHEN degree = 4 THEN '4 - Four-Way (degree=4)'
                ELSE                 '5 - Complex Hub (degree≥5)'
            END AS category,
            degree
        RETURN
            category,
            count(*) AS intersection_count
        ORDER BY category ASC
    """)


def fetch_spatial_data(driver, sample_size: int = 5000) -> pd.DataFrame:
    """
    Fetch a sample of nodes with coordinates and betweenness
    for spatial visualization.
    """
    return query_to_df(driver, """
        MATCH (i:Intersection)
        WHERE i.betweenness IS NOT NULL
        WITH i
        ORDER BY rand()
        LIMIT $sample_size
        RETURN
            i.nodeId        AS node_id,
            i.x             AS x,
            i.y             AS y,
            i.betweenness   AS betweenness,
            COUNT { (i)-[:ROAD_TO]-() } AS degree
    """, {"sample_size": sample_size})


# ─────────────────────────────────────────────────────────────
# CHART BUILDERS
# Each function takes a DataFrame and returns a Figure.
# ─────────────────────────────────────────────────────────────

# Shared color palette — consistent across all charts
COLORS = {
    "primary":    "#2196F3",
    "secondary":  "#4CAF50",
    "accent":     "#FF5722",
    "warning":    "#FF9800",
    "purple":     "#9C27B0",
    "dark":       "#263238",
    "grid":       "#ECEFF1",
    "background": "#FAFAFA",
}


def chart_degree_distribution(df: pd.DataFrame) -> go.Figure:
    """
    Bar chart: degree on x-axis, count on y-axis.
    Shows the heavily right-skewed distribution characteristic
    of sparse road networks.
    """
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df["degree"],
        y=df["intersection_count"],
        marker_color=COLORS["primary"],
        marker_line_color=COLORS["dark"],
        marker_line_width=0.5,
        hovertemplate=(
            "<b>Degree %{x}</b><br>"
            "Intersections: %{y:,}<br>"
            "<extra></extra>"
        )
    ))

    # Add a vertical line at the mean degree (~2.78)
    mean_degree = (
        (df["degree"] * df["intersection_count"]).sum()
        / df["intersection_count"].sum()
    )

    fig.add_vline(
        x=mean_degree,
        line_dash="dash",
        line_color=COLORS["accent"],
        annotation_text=f"Mean: {mean_degree:.2f}",
        annotation_position="top right",
        annotation_font_color=COLORS["accent"]
    )

    fig.update_layout(
        title={
            "text": "Degree Distribution of Road Network Intersections",
            "font": {"size": 18, "color": COLORS["dark"]}
        },
        xaxis_title="Degree (Number of Connected Roads)",
        yaxis_title="Number of Intersections",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor="white",
        xaxis=dict(
            gridcolor=COLORS["grid"],
            dtick=1
        ),
        yaxis=dict(
            gridcolor=COLORS["grid"],
            tickformat=",",
        ),
        showlegend=False,
        font=dict(family="Arial, sans-serif", size=13),
        margin=dict(t=60, b=60, l=80, r=40)
    )

    return fig


def chart_top_connected(df: pd.DataFrame) -> go.Figure:
    """
    Horizontal bar chart: top 10 intersections by degree.
    Horizontal layout is better than vertical when labels are long.
    """
    # Sort ascending so highest degree is at top of chart
    df_sorted = df.sort_values("degree", ascending=True)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df_sorted["degree"],
        y=df_sorted["intersection_label"],
        orientation="h",
        marker=dict(
            color=df_sorted["degree"],
            colorscale="Blues",
            showscale=True,
            colorbar=dict(title="Degree")
        ),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Degree: %{x}<br>"
            "<extra></extra>"
        )
    ))

    fig.update_layout(
        title={
            "text": "Top 10 Most Connected Intersections",
            "font": {"size": 18, "color": COLORS["dark"]}
        },
        xaxis_title="Degree (Number of Connected Roads)",
        yaxis_title="Intersection",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor="white",
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"]),
        showlegend=False,
        font=dict(family="Arial, sans-serif", size=13),
        margin=dict(t=60, b=60, l=150, r=40),
        height=450
    )

    return fig


def chart_connectivity_categories(df: pd.DataFrame) -> go.Figure:
    """
    Pie chart + bar chart side by side showing intersection categories.
    The pie shows proportions; the bar shows absolute counts.
    Together they give both relative and absolute perspective.
    """
    category_colors = [
        COLORS["secondary"],
        COLORS["primary"],
        COLORS["warning"],
        COLORS["accent"],
        COLORS["purple"],
    ]

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "pie"}, {"type": "bar"}]],
        subplot_titles=["Proportion", "Absolute Count"]
    )

    # Pie chart
    fig.add_trace(
        go.Pie(
            labels=df["category"],
            values=df["intersection_count"],
            marker_colors=category_colors,
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Count: %{value:,}<br>"
                "Share: %{percent}<br>"
                "<extra></extra>"
            ),
            textinfo="percent+label",
            textposition="outside",
            showlegend=False
        ),
        row=1, col=1
    )

    # Bar chart
    fig.add_trace(
        go.Bar(
            x=df["category"],
            y=df["intersection_count"],
            marker_color=category_colors,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Count: %{y:,}<br>"
                "<extra></extra>"
            ),
            showlegend=False
        ),
        row=1, col=2
    )

    fig.update_layout(
        title={
            "text": "Intersection Categories by Connectivity Level",
            "font": {"size": 18, "color": COLORS["dark"]}
        },
        plot_bgcolor=COLORS["background"],
        paper_bgcolor="white",
        font=dict(family="Arial, sans-serif", size=12),
        height=500,
        margin=dict(t=80, b=60, l=60, r=40)
    )

    fig.update_yaxes(
        gridcolor=COLORS["grid"],
        tickformat=",",
        row=1, col=2
    )

    return fig


def chart_betweenness_distribution(df: pd.DataFrame) -> go.Figure:
    """
    Histogram of betweenness centrality scores.
    Uses log scale on y-axis because the distribution is extremely
    right-skewed — a few nodes have very high scores.
    """
    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=df["betweenness"],
        nbinsx=50,
        marker_color=COLORS["purple"],
        marker_line_color=COLORS["dark"],
        marker_line_width=0.5,
        hovertemplate=(
            "Score range: %{x}<br>"
            "Count: %{y:,}<br>"
            "<extra></extra>"
        )
    ))

    fig.update_layout(
        title={
            "text": "Distribution of Betweenness Centrality Scores",
            "font": {"size": 18, "color": COLORS["dark"]}
        },
        xaxis_title="Betweenness Centrality Score",
        yaxis_title="Number of Intersections (log scale)",
        yaxis_type="log",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor="white",
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"]),
        showlegend=False,
        font=dict(family="Arial, sans-serif", size=13),
        margin=dict(t=60, b=60, l=80, r=40)
    )

    return fig


def chart_centrality_comparison(df: pd.DataFrame) -> go.Figure:
    """
    Scatter plot: betweenness vs pagerank, colored by degree.
    Reveals whether different centrality measures identify the same nodes.
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["betweenness"],
        y=df["pagerank"],
        mode="markers",
        marker=dict(
            size=6,
            color=df["degree"],
            colorscale="Viridis",
            showscale=True,
            colorbar=dict(
                title="Degree",
                thickness=15
            ),
            opacity=0.7,
            line=dict(width=0.3, color="white")
        ),
        hovertemplate=(
            "<b>Node %{customdata}</b><br>"
            "Betweenness: %{x:,.1f}<br>"
            "PageRank: %{y:.6f}<br>"
            "<extra></extra>"
        ),
        customdata=df["node_id"]
    ))

    fig.update_layout(
        title={
            "text": "Betweenness vs PageRank Centrality<br>"
                    "<sup>Color = Degree | Top 500 nodes by betweenness</sup>",
            "font": {"size": 18, "color": COLORS["dark"]}
        },
        xaxis_title="Betweenness Centrality",
        yaxis_title="PageRank Score",
        plot_bgcolor=COLORS["background"],
        paper_bgcolor="white",
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"]),
        font=dict(family="Arial, sans-serif", size=13),
        margin=dict(t=80, b=60, l=80, r=40),
        height=500
    )

    return fig


def chart_spatial_betweenness(df: pd.DataFrame) -> go.Figure:
    """
    Scatter plot using actual x/y coordinates.
    Color encodes betweenness centrality.
    This IS your road network — the geographic structure
    emerges from the coordinate data.
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["x"],
        y=df["y"],
        mode="markers",
        marker=dict(
            size=3,
            color=df["betweenness"],
            colorscale="Hot",
            showscale=True,
            colorbar=dict(
                title="Betweenness<br>Centrality",
                thickness=15
            ),
            opacity=0.8
        ),
        hovertemplate=(
            "<b>Node %{customdata[0]}</b><br>"
            "Location: (%{x}, %{y})<br>"
            "Betweenness: %{marker.color:,.1f}<br>"
            "Degree: %{customdata[1]}<br>"
            "<extra></extra>"
        ),
        customdata=df[["node_id", "degree"]].values
    ))

    fig.update_layout(
        title={
            "text": "Spatial Distribution of Betweenness Centrality",
            "font": {"size": 18, "color": COLORS["dark"]}
        },
        xaxis_title="X Coordinate",
        yaxis_title="Y Coordinate",
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="white",
        xaxis=dict(
            gridcolor="#2d2d4e",
            color="white",
            showgrid=True
        ),
        yaxis=dict(
            gridcolor="#2d2d4e",
            color="white",
            showgrid=True,
            scaleanchor="x",   # Equal aspect ratio — preserves geography
            scaleratio=1
        ),
        font=dict(family="Arial, sans-serif", size=13, color=COLORS["dark"]),
        margin=dict(t=60, b=60, l=80, r=40),
        height=600
    )

    return fig


# ─────────────────────────────────────────────────────────────
# SAVE AND DISPLAY
# ─────────────────────────────────────────────────────────────

def save_figure(fig: go.Figure, filename: str) -> None:
    """Save figure as PNG and HTML."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    png_path  = OUTPUT_DIR / f"{filename}.png"
    html_path = OUTPUT_DIR / f"{filename}.html"

    # PNG requires kaleido package
    try:
        fig.write_image(str(png_path), width=1200, height=600, scale=2)
        log.info(f"Saved PNG:  {png_path}")
    except Exception as e:
        log.warning(f"PNG save failed (install kaleido): {e}")

    # HTML is always available — interactive version
    fig.write_html(str(html_path))
    log.info(f"Saved HTML: {html_path}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log.info("Connecting to Neo4j...")
    driver = get_driver()
    log.info("Connected. Fetching data...")

    # ── Fetch all data ───────────────────────────────────────
    summary       = fetch_summary_stats(driver)
    df_degree     = fetch_degree_distribution(driver)
    df_top        = fetch_top_connected(driver, limit=10)
    df_categories = fetch_connectivity_categories(driver)
    df_between    = fetch_betweenness_distribution(driver)
    df_centrality = fetch_centrality_comparison(driver, limit=500)
    df_spatial    = fetch_spatial_data(driver, sample_size=5000)

    driver.close()

    log.info(f"Network summary: {summary}")
    log.info(f"Degree distribution: {len(df_degree)} distinct degrees")
    log.info(f"Top connected: {len(df_top)} nodes")
    log.info(f"Categories: {len(df_categories)} categories")
    log.info(f"Betweenness scores: {len(df_between):,} nodes")

    # ── Build and save all charts ────────────────────────────
    charts = [
        (chart_degree_distribution(df_degree),
         "01_degree_distribution"),

        (chart_top_connected(df_top),
         "02_top_connected_intersections"),

        (chart_connectivity_categories(df_categories),
         "03_connectivity_categories"),

        (chart_betweenness_distribution(df_between),
         "04_betweenness_distribution"),

        (chart_centrality_comparison(df_centrality),
         "05_centrality_comparison"),

        (chart_spatial_betweenness(df_spatial),
         "06_spatial_betweenness"),
    ]

    for fig, name in charts:
        log.info(f"Building chart: {name}")
        save_figure(fig, name)
        fig.show()  # Opens in browser interactively

    log.info("All charts complete.")
    log.info(f"Output saved to: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()