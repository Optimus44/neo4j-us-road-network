# US Road Network Analysis
Graph database analysis using Neo4j, Docker, and Python

![Neo4j](https://img.shields.io/badge/Neo4j-5.26-4581C3?logo=neo4j&logoColor=white)
![GDS](https://img.shields.io/badge/GDS-2.13-brightgreen)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Dash](https://img.shields.io/badge/Plotly-Dash-7D4698)

Graph database analysis of **87,575 intersections** and **121,491 roads** from the US road network. Neo4j models the network as a property graph; the GDS library runs shortest path, betweenness centrality, PageRank, and connected component algorithms. Results render in an interactive Plotly Dash dashboard.

---

## Key Findings

| Metric | Value |
|--------|-------|
| Total intersections | 87,575 |
| Total roads (after deduplication) | 121,491 |
| Average degree | 2.78 |
| Connected components | 7 |
| Giant component coverage | 99.985% |
| Duplicate edges found and merged | 470 (0.39%) |

---

## Architecture

```
roadNet.txt  →  Python ingestion  →(Bolt :7687)→  Neo4j 5.26 + GDS
                                                        ↓ Bolt :7687
Your browser ←(HTTP :8050)← Plotly Dash Dashboard ←────┘
```

Docker Compose orchestrates all containers on an internal bridge network. Containers resolve each other by service name (`neo4j`, `ingestion`, `dashboard`). Neo4j Browser is available at `localhost:7474`.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git
- 4 GB RAM available for Docker
- The `roadNet.txt` dataset file (see Dataset Format below)

---

## Dataset Format

The dataset is not included in this repository. Place it at `data/roadNet.txt`. It must follow this structure:

```
87575 121961
      0    6371    1811
      1    6390    1811
      ...
    727     728
    728     730
    ...
```

- Line 1 — header: `num_vertices  num_edges`
- Lines 2 to 87,576 — vertices: `id  x  y`
- Remaining lines — edges: `node_a  node_b`

---

## Quick Start

**1. Clone and configure**

```bash
git clone https://github.com/Optimus44/neo4j-us-road-network.git
cd us-road-network
cp .env.example .env
# Open .env and set your Neo4j password
```

**2. Place the dataset**

```bash
cp /path/to/roadNet.txt data/roadNet.txt
```

**3. Start Neo4j** — wait for `Started.` in the logs (~30 seconds)

```bash
docker compose up neo4j
# Neo4j Browser available at http://localhost:7474
```

**4. Run the ingestion pipeline**

```bash
docker compose --profile ingest up ingestion
```

Expected result:
```
Nodes — expected: 87,575  actual: 87,575  ✓ MATCH
Roads — expected: 121,961  actual: 121,491  deduplicated: 470  ✓ ACCEPTED
Import SUCCESSFUL in ~7 seconds
```

**5. Create the GDS projection and run analytics**

In Neo4j Browser (`http://localhost:7474`), run the queries in `ANALYTICS.md` in order: graph projection → betweenness → PageRank → connected components.

**6. Launch the dashboard**

```bash
docker compose --profile dashboard up dashboard
# Dashboard available at http://localhost:8050
```

---

## Project Structure

```
us-road-network/
├── docker-compose.yml       <- orchestrates all containers
├── .env.example             <- environment variable template
├── .env                     <- your credentials (gitignored)
├── ANALYTICS.md             <- GDS queries to run after ingestion
├── README.md
│
├── data/
│   └── roadNet.txt          <- dataset (not in version control)
│
├── neo4j/
│   ├── conf/neo4j.conf      <- memory and security config
│   ├── data/                <- database files (runtime, gitignored)
│   ├── logs/                <- log files (runtime, gitignored)
│   └── plugins/             <- GDS downloads here at startup
│
├── ingestion/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── ingest.py            <- parse → compute distances → batch MERGE
│
├── analysis/
│   ├── queries.py
│   ├── analytics.py
│   ├── visualize.py         <- standalone chart generation
│   └── test_pipeline.py     <- unit and integration tests
│
└── dashboard/
    ├── Dockerfile
    ├── requirements.txt
    └── app.py               <- Plotly Dash application
```

---

## Analysis Tasks

| Task | Description | Implementation |
|------|-------------|----------------|
| 1 | Count intersections and roads | `MATCH` + `count()` |
| 2 | Shortest path between intersections | `gds.shortestPath.dijkstra` |
| 3 | High-degree intersection analysis | `COUNT {}` subquery + filter |
| 4 | Betweenness centrality | `gds.betweenness.write` |
| 5 | Interactive dashboard | Plotly Dash + live Neo4j queries |
| 6 | Degree distribution chart | Distribution query + Plotly bar chart |
| 7 | Top 10 most connected intersections | Degree sort + horizontal bar chart |
| 8 | Intersection categories by degree | `CASE` classification + pie/bar combo |
| 9 | Spatial betweenness heatmap | Coordinate scatter + centrality color |

---

## Dashboard

Four interactive tabs at `http://localhost:8050`:

- **Overview** — degree distribution bar chart with mean line; connectivity categories as pie and bar
- **Degree Analysis** — top 10 most connected intersections; statistics table with percentiles
- **Centrality** — top 20 by betweenness; distribution histogram (log scale); betweenness vs PageRank scatter
- **Spatial Map** — geographic scatter plot of intersections colored by betweenness centrality

All data loads lazily on tab click and caches for instant switching on return visits.

---

## Running Tests

```bash
cd analysis
pip install neo4j
python test_pipeline.py
```

Expected: 4 tests passing — Euclidean distance, file parser, degree math, Neo4j integration.

---

## Technical Notes

**Cypher version.** This project uses Neo4j 5.x syntax. Degree calculations use `COUNT { (n)-[:REL]-() }` rather than the deprecated `size()` pattern expression.

**Bidirectional deduplication.** The source dataset contains 470 bidirectional duplicate edge pairs. Neo4j's undirected `MERGE` reduces these to single relationships, producing 121,491 unique roads from 121,961 raw edges.

**GDS sampling.** Betweenness centrality uses approximate computation with 100 sampled source nodes and seed 42 for reproducibility.

**Memory.** Neo4j is configured with 1 GB heap and 512 MB page cache. The GDS projection requires approximately 30 MB for the in-memory graph.

---

## Troubleshooting

**Neo4j won't start**
```bash
docker compose logs neo4j
# Look for Java errors or memory issues
# Reduce heap/pagecache in neo4j/conf/neo4j.conf if needed
```

**GDS plugin not loading**
```bash
docker compose logs neo4j | grep -i "gds\|plugin\|error"
```

**Ingestion exits immediately**
```bash
docker compose logs ingestion
# Verify data/roadNet.txt exists and has the correct format
```

**Dashboard charts are empty**
```bash
# Run the analytics write queries in Neo4j Browser first, then verify:
MATCH (i:Intersection {nodeId: 0})
RETURN i.betweenness, i.pagerank, i.componentId
```

**Port already in use**
```bash
# Mac/Linux
lsof -i :7474
# Windows
netstat -ano | findstr :7474
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
NEO4J_URI=bolt://neo4j:7687
DASH_PORT=8050
```

Use `bolt://neo4j:7687` inside Docker. Use `bolt://localhost:7687` when running Python scripts directly on your machine.

---

## Acknowledgements

- [Neo4j Graph Database](https://neo4j.com) and GDS library
- [Plotly Dash](https://dash.plotly.com)
- Dataset provided as part of course assignment

---

*Neo4j 5.26 · GDS 2.13 · Docker Compose · Python 3.11 · Plotly Dash 2.17*