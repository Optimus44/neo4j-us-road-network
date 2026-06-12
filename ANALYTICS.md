# Analytics Reference
GDS queries for the US Road Network project.
Run these in Neo4j Browser (`http://localhost:7474`) after ingestion completes.
Execute them **in order** — each step depends on the previous one.

---

## Step 1 — Create the GDS Graph Projection

This loads your Neo4j graph into GDS's in-memory format.
All algorithms in Steps 2–6 operate on this projection.

> **Note:** The projection lives in memory and is lost when Neo4j restarts.
> Re-run this step any time you restart the container before running algorithms.

```cypher
// Drop the projection if it already exists (safe to run on first run too)
CALL gds.graph.drop('roadNetwork', false)
YIELD graphName;

// Create the projection
CALL gds.graph.project(
    'roadNetwork',
    'Intersection',
    {
        ROAD_TO: { orientation: 'UNDIRECTED' }
    },
    {
        relationshipProperties: 'distance'
    }
)
YIELD graphName, nodeCount, relationshipCount, projectMillis
RETURN graphName, nodeCount, relationshipCount, projectMillis
```

**Expected result:**

| graphName | nodeCount | relationshipCount | projectMillis |
|-----------|-----------|-------------------|---------------|
| roadNetwork | 87575 | 242982 | ~500–2000 |

`relationshipCount` is roughly double your road count because UNDIRECTED
orientation stores each relationship in both traversal directions internally.

---

## Step 2 — Betweenness Centrality (Task 4)

Measures how often each intersection appears on shortest paths between
other pairs. High score = critical bottleneck or bridge in the network.

```cypher
// Write scores to nodes as the 'betweenness' property
CALL gds.betweenness.write('roadNetwork', {
    writeProperty: 'betweenness',
    samplingSize: 100,
    samplingSeed:  42
})
YIELD nodePropertiesWritten, computeMillis
RETURN nodePropertiesWritten, computeMillis
```

**Expected result:** `nodePropertiesWritten: 87575`

```cypher
// Verify — top 20 intersections by betweenness
MATCH (i:Intersection)
WHERE i.betweenness IS NOT NULL
RETURN
    i.nodeId                    AS intersection_id,
    round(i.betweenness, 2)     AS betweenness_score,
    COUNT { (i)-[:ROAD_TO]-() } AS degree
ORDER BY i.betweenness DESC
LIMIT 20
```

```cypher
// Distribution statistics
MATCH (i:Intersection)
WHERE i.betweenness IS NOT NULL
RETURN
    round(min(i.betweenness), 2)                  AS min_score,
    round(max(i.betweenness), 2)                  AS max_score,
    round(avg(i.betweenness), 2)                  AS avg_score,
    round(percentileCont(i.betweenness, 0.95), 2) AS p95_score,
    count(CASE WHEN i.betweenness = 0
               THEN 1 END)                         AS zero_score_count
```

---

## Step 3 — PageRank

Measures intersection importance based on the importance of its neighbors.
High score = well-connected to other important intersections.

```cypher
// Write scores to nodes as the 'pagerank' property
CALL gds.pageRank.write('roadNetwork', {
    writeProperty:  'pagerank',
    maxIterations:  20,
    dampingFactor:  0.85
})
YIELD nodePropertiesWritten, ranIterations, didConverge, computeMillis
RETURN nodePropertiesWritten, ranIterations, didConverge, computeMillis
```

**Expected result:** `nodePropertiesWritten: 87575`, `didConverge: true`

If `didConverge` is false, increase `maxIterations` to 40 and re-run.

```cypher
// Verify — top 20 intersections by PageRank
MATCH (i:Intersection)
WHERE i.pagerank IS NOT NULL
RETURN
    i.nodeId                    AS intersection_id,
    round(i.pagerank, 6)        AS pagerank_score,
    COUNT { (i)-[:ROAD_TO]-() } AS degree
ORDER BY i.pagerank DESC
LIMIT 20
```

---

## Step 4 — Closeness Centrality

Measures how quickly each intersection can reach all others.
High score = geographically central position in the network.

```cypher
// Write scores to nodes as the 'closeness' property
CALL gds.closeness.write('roadNetwork', {
    writeProperty: 'closeness'
})
YIELD nodePropertiesWritten, computeMillis
RETURN nodePropertiesWritten, computeMillis
```

**Expected result:** `nodePropertiesWritten: 87575`

> **Note:** Closeness may take 1–3 minutes on 87k nodes. This is normal.

```cypher
// Verify — top 10 most central intersections
MATCH (i:Intersection)
WHERE i.closeness IS NOT NULL
RETURN
    i.nodeId                AS intersection_id,
    i.x                     AS x,
    i.y                     AS y,
    round(i.closeness, 6)   AS closeness_score
ORDER BY i.closeness DESC
LIMIT 10
```

---

## Step 5 — Weakly Connected Components

Identifies groups of intersections that are internally connected but
disconnected from the rest of the network.

```cypher
// Write component IDs to nodes as the 'componentId' property
CALL gds.wcc.write('roadNetwork', {
    writeProperty: 'componentId'
})
YIELD nodePropertiesWritten, componentCount, computeMillis
RETURN nodePropertiesWritten, componentCount, computeMillis
```

**Expected result:** `componentCount: 7`

```cypher
// Verify — size of each component
MATCH (i:Intersection)
WHERE i.componentId IS NOT NULL
WITH i.componentId AS component, count(*) AS size
RETURN component, size
ORDER BY size DESC
LIMIT 10
```

**Expected:** One giant component with ~87,562 nodes, six small ones with 2–4 nodes each.

```cypher
// What percentage of the network is in the giant component?
MATCH (i:Intersection)
WHERE i.componentId IS NOT NULL
WITH i.componentId AS comp, count(*) AS size
WITH max(size) AS giant_size
RETURN
    giant_size                                          AS giant_component,
    87575                                               AS total_nodes,
    round(toFloat(giant_size) / 87575 * 100, 3)        AS pct_of_network
```

---

## Step 6 — Verify All Properties Written

Run this after completing Steps 2–5 to confirm every property exists on your nodes.

```cypher
MATCH (i:Intersection)
WHERE i.nodeId IN [0, 100, 1000, 50000]
RETURN
    i.nodeId        AS node_id,
    i.x             AS x,
    i.y             AS y,
    round(i.betweenness, 2)  AS betweenness,
    round(i.pagerank, 6)     AS pagerank,
    round(i.closeness, 6)    AS closeness,
    i.componentId            AS component_id
ORDER BY i.nodeId
```

All five analytics columns should be non-null. If any are null, re-run
the corresponding step above.

---

## Bonus — Shortest Path (Task 2)

Find the shortest path between two intersections using Dijkstra's algorithm.
Replace `0` and `50000` with any two node IDs you want to test.

```cypher
// Basic shortest path
MATCH (source:Intersection {nodeId: 0}),
      (target:Intersection {nodeId: 50000})
CALL gds.shortestPath.dijkstra.stream('roadNetwork', {
    sourceNode:                 source,
    targetNode:                 target,
    relationshipWeightProperty: 'distance'
})
YIELD totalCost, nodeIds
RETURN
    size(nodeIds) - 1                                        AS hops,
    round(totalCost, 2)                                      AS total_distance,
    [id IN nodeIds | gds.util.asNode(id).nodeId]             AS full_path
```

```cypher
// Find two geographically distant nodes to use as source/target
// Lowest coordinate sum
MATCH (i:Intersection)
RETURN i.nodeId AS node_id, i.x, i.y, (i.x + i.y) AS coord_sum
ORDER BY coord_sum ASC
LIMIT 3
```

```cypher
// Highest coordinate sum
MATCH (i:Intersection)
RETURN i.nodeId AS node_id, i.x, i.y, (i.x + i.y) AS coord_sum
ORDER BY coord_sum DESC
LIMIT 3
```

---

## Bonus — Three Centrality Measures Side by Side

Compare betweenness, PageRank, and degree for the most critical intersections.
Intersections appearing high in all three measures are doubly critical.

```cypher
MATCH (i:Intersection)
WHERE i.betweenness IS NOT NULL
  AND i.pagerank    IS NOT NULL
WITH i, COUNT { (i)-[:ROAD_TO]-() } AS degree
RETURN
    i.nodeId                    AS intersection_id,
    degree,
    round(i.betweenness, 2)     AS betweenness,
    round(i.pagerank, 6)        AS pagerank,
    round(i.closeness, 6)       AS closeness
ORDER BY i.betweenness DESC
LIMIT 20
```

---

## Bonus — Degree Statistics

```cypher
MATCH (i:Intersection)
WITH COUNT { (i)-[:ROAD_TO]-() } AS degree
RETURN
    min(degree)                    AS min_degree,
    max(degree)                    AS max_degree,
    round(avg(degree), 4)          AS avg_degree,
    percentileCont(degree, 0.50)   AS median,
    percentileCont(degree, 0.90)   AS p90,
    percentileCont(degree, 0.99)   AS p99
```

---

## Quick Reference — Re-running After a Restart

Neo4j retains node and relationship data across restarts (volumes are configured).
Analytics properties (`betweenness`, `pagerank`, etc.) are also persisted as node properties.

The **only** thing lost on restart is the GDS in-memory projection.
Re-run Step 1 only, then all algorithms are available again immediately.

```cypher
// One-liner to check projection status after a restart
CALL gds.graph.list()
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
// If empty: re-run Step 1
// If present: ready to use
```