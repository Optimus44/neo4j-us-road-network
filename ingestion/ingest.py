"""
ingest.py — US Road Network Data Ingestion Pipeline
=====================================================
Reads the road network dataset, validates it, computes
Euclidean distances, and loads the graph into Neo4j.

Dataset format:
  Line 1:        <num_vertices> <num_edges>
  Lines 2..V+1:  <node_id> <x> <y>
  Lines V+2..end: <node_a> <node_b>
"""

import os
import sys
import math
import time
import logging
from pathlib import Path

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError
from tqdm import tqdm


# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# Read everything from environment variables so this script
# works identically inside Docker and outside Docker.
# ─────────────────────────────────────────────────────────────

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "roadnetwork2024")
DATA_FILE      = os.getenv("DATA_FILE",      "/data/roadNet.txt")
BATCH_SIZE     = int(os.getenv("BATCH_SIZE", "500"))


# ─────────────────────────────────────────────────────────────
# LOGGING
# Professional scripts always log what they're doing.
# This makes debugging much easier when something goes wrong.
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# STEP 1 — PARSE THE DATASET FILE
# ─────────────────────────────────────────────────────────────

def parse_dataset(filepath: str) -> tuple[list, list]:
    """
    Parse the road network file into vertices and edges.

    Returns:
        vertices: list of (node_id, x, y) tuples
        edges:    list of (node_a, node_b) tuples
    """
    path = Path(filepath)

    if not path.exists():
        log.error(f"Dataset file not found: {filepath}")
        log.error("Make sure the data/ directory is mounted correctly.")
        sys.exit(1)

    log.info(f"Opening dataset: {filepath}")
    log.info(f"File size: {path.stat().st_size / 1_000_000:.1f} MB")

    vertices = []
    edges    = []

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # ── Parse header ────────────────────────────────────────
    # Line 0: "<num_vertices> <num_edges>"
    header = lines[0].strip().split()
    expected_vertices = int(header[0])
    expected_edges    = int(header[1])

    log.info(f"Header declares: {expected_vertices:,} vertices, "
             f"{expected_edges:,} edges")

    # ── Parse vertex section ─────────────────────────────────
    # Lines 1 to expected_vertices (inclusive)
    log.info("Parsing vertex section...")

    for i in range(1, expected_vertices + 1):
        parts = lines[i].strip().split()

        # Validate: each vertex line must have exactly 3 values
        if len(parts) != 3:
            log.error(f"Malformed vertex line {i+1}: '{lines[i].rstrip()}'")
            sys.exit(1)

        node_id = int(parts[0])
        x       = float(parts[1])
        y       = float(parts[2])

        # Validate: node IDs must be sequential from 0
        if node_id != i - 1:
            log.error(f"Unexpected node_id {node_id} at line {i+1} "
                      f"(expected {i-1})")
            sys.exit(1)

        vertices.append((node_id, x, y))

    log.info(f"Parsed {len(vertices):,} vertices")

    # ── Parse edge section ───────────────────────────────────
    # Lines expected_vertices+1 to end
    log.info("Parsing edge section...")

    edge_start = expected_vertices + 1

    for i in range(edge_start, len(lines)):
        line = lines[i].strip()

        # Skip blank lines (e.g. trailing newline at end of file)
        if not line:
            continue

        parts = line.split()

        # Validate: each edge line must have exactly 2 values
        if len(parts) != 2:
            log.error(f"Malformed edge line {i+1}: '{lines[i].rstrip()}'")
            sys.exit(1)

        node_a = int(parts[0])
        node_b = int(parts[1])

        # Validate: both node IDs must be within range
        if node_a >= expected_vertices or node_b >= expected_vertices:
            log.error(f"Edge references out-of-range node: "
                      f"{node_a} -- {node_b}")
            sys.exit(1)

        # Avoid self-loops (a road from a node to itself makes no sense)
        if node_a == node_b:
            log.warning(f"Skipping self-loop at node {node_a}")
            continue

        edges.append((node_a, node_b))

    log.info(f"Parsed {len(edges):,} edges")

    # ── Validate totals ──────────────────────────────────────
    if len(vertices) != expected_vertices:
        log.error(f"Vertex count mismatch: expected {expected_vertices}, "
                  f"got {len(vertices)}")
        sys.exit(1)

    if len(edges) != expected_edges:
        log.warning(f"Edge count mismatch: expected {expected_edges}, "
                    f"got {len(edges)}")
        # Warning not error — dataset may have self-loops we skipped

    log.info("Dataset validation passed")
    return vertices, edges


# ─────────────────────────────────────────────────────────────
# STEP 2 — COMPUTE EUCLIDEAN DISTANCES
# ─────────────────────────────────────────────────────────────

def compute_distance(x1: float, y1: float,
                     x2: float, y2: float) -> float:
    """
    Euclidean distance between two points in 2D space.
    sqrt((x2-x1)^2 + (y2-y1)^2)
    """
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def build_edge_records(vertices: list, edges: list) -> list:
    """
    Combine edge pairs with computed distances.

    For each edge (a, b), looks up coordinates of both endpoints
    and computes the Euclidean distance.

    Returns:
        List of dicts: {node_a, node_b, distance}
    """
    log.info("Computing Euclidean distances for all edges...")

    # Build a fast coordinate lookup: {node_id: (x, y)}
    # Using a dict means O(1) lookup instead of O(n) list scan
    coords = {v[0]: (v[1], v[2]) for v in vertices}

    edge_records = []
    for node_a, node_b in edges:
        x1, y1 = coords[node_a]
        x2, y2 = coords[node_b]
        dist = compute_distance(x1, y1, x2, y2)
        edge_records.append({
            "node_a":   node_a,
            "node_b":   node_b,
            "distance": round(dist, 4)
        })

    # Quick sanity check: show a few computed distances
    log.info("Sample distances (first 3 edges):")
    for rec in edge_records[:3]:
        log.info(f"  {rec['node_a']} → {rec['node_b']}: "
                 f"{rec['distance']:.4f} units")

    log.info(f"Distance computation complete for {len(edge_records):,} edges")
    return edge_records


# ─────────────────────────────────────────────────────────────
# STEP 3 — CONNECT TO NEO4J (WITH RETRY LOGIC)
# ─────────────────────────────────────────────────────────────

def connect_to_neo4j(max_retries: int = 15,
                     retry_delay: int = 10) -> GraphDatabase.driver:
    """
    Connect to Neo4j with retry logic.

    Neo4j takes 20-60 seconds to fully initialize. If the ingestion
    container starts before Neo4j is ready, we wait and retry rather
    than crashing immediately.
    """
    log.info(f"Connecting to Neo4j at {NEO4J_URI}")

    for attempt in range(1, max_retries + 1):
        try:
            driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD)
            )
            # verify_connectivity() actually tests the connection
            # (just creating the driver object doesn't connect yet)
            driver.verify_connectivity()
            log.info(f"Connected to Neo4j successfully "
                     f"(attempt {attempt}/{max_retries})")
            return driver

        except AuthError:
            # Wrong credentials — retrying won't help
            log.error("Authentication failed. Check NEO4J_USER and "
                      "NEO4J_PASSWORD in your .env file.")
            sys.exit(1)

        except ServiceUnavailable:
            if attempt < max_retries:
                log.warning(f"Neo4j not ready yet. "
                            f"Retrying in {retry_delay}s "
                            f"(attempt {attempt}/{max_retries})...")
                time.sleep(retry_delay)
            else:
                log.error("Could not connect to Neo4j after "
                          f"{max_retries} attempts. Giving up.")
                sys.exit(1)


# ─────────────────────────────────────────────────────────────
# STEP 4 — CREATE SCHEMA (CONSTRAINTS AND INDEXES)
# ─────────────────────────────────────────────────────────────

def create_schema(driver: GraphDatabase.driver) -> None:
    """
    Create the unique constraint and indexes before importing data.

    The unique constraint on nodeId:
    1. Guarantees no duplicate intersections
    2. Automatically creates a B-tree index on nodeId
    3. Makes MERGE operations fast (O(log n) instead of O(n))
    """
    log.info("Creating schema constraints and indexes...")

    with driver.session() as session:
        session.run("""
            CREATE CONSTRAINT intersection_nodeId_unique
            IF NOT EXISTS
            FOR (i:Intersection)
            REQUIRE i.nodeId IS UNIQUE
        """)

        session.run("""
            CREATE INDEX intersection_x_idx
            IF NOT EXISTS
            FOR (i:Intersection)
            ON (i.x)
        """)

        session.run("""
            CREATE INDEX intersection_y_idx
            IF NOT EXISTS
            FOR (i:Intersection)
            ON (i.y)
        """)

    log.info("Schema ready")


# ─────────────────────────────────────────────────────────────
# STEP 5 — LOAD NODES IN BATCHES
# ─────────────────────────────────────────────────────────────

# The Cypher query for batch node creation.
# UNWIND turns a list parameter into individual rows — 
# it's the key to efficient batch loading in Neo4j.
#
# MERGE finds the node if it exists, creates it if it doesn't.
# ON CREATE SET only runs when the node is newly created.
# This makes the script safe to run multiple times.

MERGE_NODES_QUERY = """
UNWIND $batch AS row
MERGE (i:Intersection {nodeId: row.nodeId})
ON CREATE SET
    i.x = row.x,
    i.y = row.y
"""

def load_nodes(driver: GraphDatabase.driver,
               vertices: list) -> None:
    """
    Load all intersection nodes into Neo4j in batches.
    """
    log.info(f"Loading {len(vertices):,} intersection nodes "
             f"(batch size: {BATCH_SIZE})...")

    # Convert vertex tuples to dicts that Cypher can receive as parameters
    node_records = [
        {"nodeId": v[0], "x": v[1], "y": v[2]}
        for v in vertices
    ]

    total_loaded = 0

    with driver.session() as session:
        # tqdm wraps the range and shows a progress bar
        for start in tqdm(range(0, len(node_records), BATCH_SIZE),
                          desc="Nodes", unit="batch"):

            batch = node_records[start : start + BATCH_SIZE]

            session.run(MERGE_NODES_QUERY, batch=batch)
            total_loaded += len(batch)

    log.info(f"Node loading complete: {total_loaded:,} nodes processed")


# ─────────────────────────────────────────────────────────────
# STEP 6 — LOAD RELATIONSHIPS IN BATCHES
# ─────────────────────────────────────────────────────────────

# The Cypher query for batch relationship creation.
#
# MATCH (not MERGE) for the nodes — they already exist from step 5,
# and MATCH is faster since we don't need to check for creation.
#
# MERGE for the relationship — prevents duplicates if the script
# is run twice. MERGE on a relationship checks both the type
# and the connected nodes.
#
# ON CREATE SET only sets distance when the relationship is new.

MERGE_RELS_QUERY = """
UNWIND $batch AS row
MATCH (a:Intersection {nodeId: row.node_a})
MATCH (b:Intersection {nodeId: row.node_b})
MERGE (a)-[r:ROAD_TO]-(b)
ON CREATE SET r.distance = row.distance
"""

def load_relationships(driver: GraphDatabase.driver,
                       edge_records: list) -> None:
    """
    Load all road relationships into Neo4j in batches.

    Note: relationships are loaded AFTER all nodes are loaded.
    This is important — MATCH will fail if a node doesn't exist yet.
    """
    log.info(f"Loading {len(edge_records):,} road relationships "
             f"(batch size: {BATCH_SIZE})...")

    total_loaded = 0

    with driver.session() as session:
        for start in tqdm(range(0, len(edge_records), BATCH_SIZE),
                          desc="Roads", unit="batch"):

            batch = edge_records[start : start + BATCH_SIZE]
            session.run(MERGE_RELS_QUERY, batch=batch)
            total_loaded += len(batch)

    log.info(f"Relationship loading complete: {total_loaded:,} roads processed")


# ─────────────────────────────────────────────────────────────
# STEP 7 — VERIFY THE IMPORT
# ─────────────────────────────────────────────────────────────

def verify_import(driver: GraphDatabase.driver,
                  expected_nodes: int,
                  expected_edges: int) -> bool:
    """
    Verify the import. Relationships may be fewer than raw edge count
    because bidirectional duplicates in the source file are merged
    into single undirected relationships — which is correct behavior.
    """
    log.info("Verifying import...")

    with driver.session() as session:
        node_result = session.run(
            "MATCH (i:Intersection) RETURN count(i) AS n"
        )
        actual_nodes = node_result.single()["n"]

        rel_result = session.run(
            "MATCH ()-[r:ROAD_TO]->() RETURN count(r) AS r"
        )
        actual_rels = rel_result.single()["r"]

    # Nodes must match exactly
    nodes_ok = actual_nodes == expected_nodes

    # Relationships may be fewer due to bidirectional deduplication.
    # We accept any count between (expected - expected*0.01) and expected.
    # A 1% tolerance catches legitimate deduplication without hiding
    # real errors like a truncated file.
    dedup_threshold = int(expected_edges * 0.99)
    rels_ok = dedup_threshold <= actual_rels <= expected_edges

    log.info("Verification results:")
    log.info(f"  Nodes — expected: {expected_nodes:,}  "
             f"actual: {actual_nodes:,}  "
             f"{'✓ MATCH' if nodes_ok else '✗ MISMATCH'}")
    log.info(f"  Roads — expected: {expected_edges:,}  "
             f"actual: {actual_rels:,}  "
             f"deduplicated: {expected_edges - actual_rels:,}  "
             f"{'✓ ACCEPTED' if rels_ok else '✗ MISMATCH'}")

    if rels_ok and nodes_ok:
        log.info(f"  Note: {expected_edges - actual_rels:,} bidirectional "
                 f"duplicate roads were correctly merged into single "
                 f"undirected relationships.")

    return nodes_ok and rels_ok

# ─────────────────────────────────────────────────────────────
# STEP 8 — CLEAR EXISTING DATA (OPTIONAL)
# ─────────────────────────────────────────────────────────────

def clear_database(driver: GraphDatabase.driver) -> None:
    """
    Remove all existing nodes and relationships.
    Called only if --clear flag is passed, to allow re-importing.

    DETACH DELETE removes the node AND all its relationships.
    We use CALL { } IN TRANSACTIONS to avoid memory issues
    when deleting large numbers of nodes.
    """
    log.warning("Clearing existing database data...")

    with driver.session() as session:
        session.run("""
            MATCH (n)
            CALL { WITH n DETACH DELETE n }
            IN TRANSACTIONS OF 1000 ROWS
        """)

    log.warning("Database cleared")


# ─────────────────────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("US Road Network — Ingestion Pipeline")
    log.info("=" * 60)

    # Check for --clear flag
    clear_first = "--clear" in sys.argv

    # ── Step 1: Parse the dataset ────────────────────────────
    vertices, edges = parse_dataset(DATA_FILE)

    # ── Step 2: Compute distances ────────────────────────────
    edge_records = build_edge_records(vertices, edges)

    # ── Step 3: Connect to Neo4j ─────────────────────────────
    driver = connect_to_neo4j()

    # ── Step 4: Optionally clear existing data ───────────────
    if clear_first:
        clear_database(driver)

    # ── Step 5: Create schema ────────────────────────────────
    create_schema(driver)

    # ── Step 6: Load nodes ───────────────────────────────────
    load_nodes(driver, vertices)

    # ── Step 7: Load relationships ───────────────────────────
    load_relationships(driver, edge_records)

    # ── Step 8: Verify ───────────────────────────────────────
    success = verify_import(driver, len(vertices), len(edges))

    driver.close()

    elapsed = time.time() - start_time
    log.info("=" * 60)

    if success:
        log.info(f"Import SUCCESSFUL in {elapsed:.1f} seconds")
        log.info("Your graph is ready in Neo4j.")
        sys.exit(0)
    else:
        log.error(f"Import completed with MISMATCHES after {elapsed:.1f}s")
        log.error("Check the logs above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()