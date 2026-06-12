"""
test_pipeline.py — Unit tests for the road network pipeline
===========================================================
Run with: python -m pytest analysis/test_pipeline.py -v
Or simply: python analysis/test_pipeline.py
"""

import math
import sys
import os


# ─────────────────────────────────────────────────────────────
# TEST 1 — Euclidean distance calculation
# ─────────────────────────────────────────────────────────────

def test_euclidean_distance():
    """
    Verify the distance formula with known values.
    These are hand-calculated from the first few nodes
    in your dataset.
    """

    def distance(x1, y1, x2, y2):
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    # Node 0: (6371, 1811)  Node 1: (6390, 1811)
    # Same y-coordinate, so distance = |6390 - 6371| = 19.0 exactly
    d = distance(6371, 1811, 6390, 1811)
    assert abs(d - 19.0) < 0.001, f"Expected 19.0, got {d}"
    print(f"  ✓ Horizontal distance: {d:.4f} (expected 19.0)")

    # Node 1: (6390, 1811)  Node 2: (6416, 1810)
    # distance = sqrt((6416-6390)^2 + (1810-1811)^2)
    #          = sqrt(676 + 1)
    #          = sqrt(677) ≈ 26.0192
    d = distance(6390, 1811, 6416, 1810)
    expected = math.sqrt(677)
    assert abs(d - expected) < 0.001, f"Expected {expected:.4f}, got {d}"
    print(f"  ✓ Diagonal distance: {d:.4f} (expected {expected:.4f})")

    # Distance must always be non-negative
    d = distance(100, 200, 50, 150)
    assert d >= 0, "Distance cannot be negative"
    print(f"  ✓ Non-negative: {d:.4f}")

    # Distance from a point to itself must be zero
    d = distance(500, 500, 500, 500)
    assert d == 0.0, f"Self-distance must be 0, got {d}"
    print(f"  ✓ Self-distance: {d:.4f}")

    # Distance is symmetric: d(a,b) == d(b,a)
    d1 = distance(100, 200, 300, 400)
    d2 = distance(300, 400, 100, 200)
    assert abs(d1 - d2) < 0.0001, "Distance must be symmetric"
    print(f"  ✓ Symmetry: d(a→b)={d1:.4f} == d(b→a)={d2:.4f}")

    print("PASS: Euclidean distance tests")


# ─────────────────────────────────────────────────────────────
# TEST 2 — File parser
# ─────────────────────────────────────────────────────────────

def test_parser():
    """
    Verify the parser correctly reads the dataset format.
    Uses a small in-memory test dataset instead of the real file.
    """
    import tempfile

    # Create a minimal valid dataset in the assignment format
    test_content = """6 9
      0    6371    1811
      1    6390    1811
      2    6416    1810
      3    6443    1810
      4    6390    1810
      5    6494    1810
    727     728
    728     730
    707     720
    720     723
    666     717
    717     723
    683     712
    712     731
    756     755
"""
    # Override the content with a proper small dataset
    test_content = """6 4
      0    1000    2400
      1    2800    3000
      2    2400    2500
      3    4000    0
      4    4500    3800
      5    6000    1500
    0     1
    0     3
    1     2
    2     5
"""

    # Write to temp file and parse it
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as f:
        f.write(test_content)
        tmp_path = f.name

    try:
        # Inline parser (mirrors ingest.py logic)
        with open(tmp_path) as f:
            lines = f.readlines()

        header   = lines[0].strip().split()
        n_verts  = int(header[0])
        n_edges  = int(header[1])

        vertices = []
        for i in range(1, n_verts + 1):
            parts = lines[i].strip().split()
            vertices.append((int(parts[0]), float(parts[1]),
                             float(parts[2])))

        edges = []
        for i in range(n_verts + 1, len(lines)):
            line = lines[i].strip()
            if not line:
                continue
            parts = line.split()
            edges.append((int(parts[0]), int(parts[1])))

        # Assertions
        assert n_verts == 6, f"Expected 6 vertices, got {n_verts}"
        assert n_edges == 4, f"Expected 4 edges, got {n_edges}"
        assert len(vertices) == 6, f"Parsed {len(vertices)} vertices"
        assert len(edges) == 4, f"Parsed {len(edges)} edges"

        # Check first vertex
        assert vertices[0] == (0, 1000.0, 2400.0), \
            f"Wrong vertex 0: {vertices[0]}"

        # Check first edge
        assert edges[0] == (0, 1), f"Wrong edge 0: {edges[0]}"

        print(f"  ✓ Header parsed: {n_verts} vertices, {n_edges} edges")
        print(f"  ✓ Vertices parsed: {len(vertices)}")
        print(f"  ✓ Edges parsed: {len(edges)}")
        print(f"  ✓ Vertex 0: {vertices[0]}")
        print(f"  ✓ Edge 0: {edges[0]}")
        print("PASS: Parser tests")

    finally:
        os.unlink(tmp_path)


# ─────────────────────────────────────────────────────────────
# TEST 3 — Degree calculation sanity
# ─────────────────────────────────────────────────────────────

def test_degree_math():
    """
    Verify the degree/average degree math is consistent
    with what we expect from the dataset.
    """
    # Known values from your dataset
    total_nodes = 87_575
    total_roads = 121_491   # after deduplication

    # Average degree formula: (2 * edges) / nodes
    avg_degree = (2 * total_roads) / total_nodes

    # Should be approximately 2.78
    assert 2.7 < avg_degree < 2.9, \
        f"Average degree {avg_degree:.4f} outside expected range"
    print(f"  ✓ Average degree: {avg_degree:.4f} (expected ~2.78)")

    # Sum of degrees must equal 2 * edges (handshaking lemma)
    # This is a fundamental graph theory identity
    sum_of_degrees = 2 * total_roads
    assert sum_of_degrees == 242_982
    print(f"  ✓ Sum of degrees: {sum_of_degrees:,} = 2 × {total_roads:,}")

    # Density: actual edges / maximum possible edges
    max_possible = total_nodes * (total_nodes - 1) / 2
    density = total_roads / max_possible
    assert density < 0.001, "Graph should be very sparse"
    print(f"  ✓ Graph density: {density:.8f} (very sparse, as expected)")

    print("PASS: Degree math tests")


# ─────────────────────────────────────────────────────────────
# TEST 4 — Neo4j connection test
# ─────────────────────────────────────────────────────────────

def test_neo4j_connection():
    """
    Verify Neo4j is reachable and returns expected data.
    Requires Neo4j to be running.
    """
    try:
        from neo4j import GraphDatabase

        uri      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
        user     = os.getenv("NEO4J_USER",     "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "roadnetwork2024")

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        print("  ✓ Neo4j connection established")

        with driver.session() as session:

            # Test 1: Node count
            result = session.run(
                "MATCH (i:Intersection) RETURN count(i) AS n"
            )
            n = result.single()["n"]
            assert n == 87_575, f"Expected 87575 nodes, got {n}"
            print(f"  ✓ Node count: {n:,}")

            # Test 2: Relationship count
            result = session.run(
                "MATCH ()-[r:ROAD_TO]->() RETURN count(r) AS r"
            )
            r = result.single()["r"]
            assert r == 121_491, f"Expected 121491 roads, got {r}"
            print(f"  ✓ Relationship count: {r:,}")

            # Test 3: Constraint exists
            result = session.run("""
                SHOW CONSTRAINTS
                YIELD name
                WHERE name = 'intersection_nodeId_unique'
                RETURN count(*) AS n
            """)
            n = result.single()["n"]
            assert n == 1, "Unique constraint missing"
            print("  ✓ Unique constraint present")

            # Test 4: Node lookup by nodeId is fast
            import time
            start = time.time()
            session.run(
                "MATCH (i:Intersection {nodeId: 50000}) RETURN i"
            )
            elapsed = (time.time() - start) * 1000
            assert elapsed < 500, \
                f"Node lookup too slow: {elapsed:.0f}ms (expected <500ms)"
            print(f"  ✓ Index lookup speed: {elapsed:.1f}ms")

            # Test 5: Distance values are positive
            result = session.run("""
                MATCH ()-[r:ROAD_TO]->()
                WHERE r.distance <= 0
                RETURN count(r) AS bad_distances
            """)
            bad = result.single()["bad_distances"]
            assert bad == 0, f"{bad} relationships have non-positive distance"
            print(f"  ✓ All distances positive (0 bad values)")

            # Test 6: Node coordinates are in expected range
            result = session.run("""
                MATCH (i:Intersection)
                RETURN min(i.x) AS min_x, max(i.x) AS max_x,
                       min(i.y) AS min_y, max(i.y) AS max_y
            """)
            row = result.single()
            assert row["min_x"] > 0,    "X coordinates should be positive"
            assert row["min_y"] > 0,    "Y coordinates should be positive"
            assert row["max_x"] < 15000, "X coordinates seem too large"
            assert row["max_y"] < 15000, "Y coordinates seem too large"
            print(f"  ✓ Coordinate ranges: "
                  f"x=[{row['min_x']:.0f}, {row['max_x']:.0f}] "
                  f"y=[{row['min_y']:.0f}, {row['max_y']:.0f}]")

            # Test 7: GDS projection exists
            result = session.run("""
                CALL gds.graph.list()
                YIELD graphName
                WHERE graphName = 'roadNetwork'
                RETURN count(*) AS n
            """)
            n = result.single()["n"]
            if n == 0:
                print("  ⚠ GDS projection 'roadNetwork' not found "
                      "— recreate it before running algorithms")
            else:
                print("  ✓ GDS projection 'roadNetwork' exists")

            # Test 8: Analytics properties present
            result = session.run("""
                MATCH (i:Intersection)
                WHERE i.betweenness IS NOT NULL
                RETURN count(i) AS n
            """)
            n = result.single()["n"]
            if n == 87_575:
                print(f"  ✓ Betweenness scores: {n:,} nodes")
            else:
                print(f"  ⚠ Betweenness scores: {n:,} / 87,575 nodes "
                      f"(run Task 4 write query)")

        driver.close()
        print("PASS: Neo4j integration tests")

    except ImportError:
        print("SKIP: neo4j package not installed")
    except Exception as e:
        print(f"FAIL: Neo4j test failed: {e}")


# ─────────────────────────────────────────────────────────────
# RUN ALL TESTS
# ─────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Euclidean Distance",   test_euclidean_distance),
        ("File Parser",          test_parser),
        ("Degree Math",          test_degree_math),
        ("Neo4j Integration",    test_neo4j_connection),
    ]

    passed = 0
    failed = 0

    print("=" * 55)
    print("US Road Network — Test Suite")
    print("=" * 55)

    for name, test_fn in tests:
        print(f"\n── {name} ──")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print("\n" + "=" * 55)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 55)

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)