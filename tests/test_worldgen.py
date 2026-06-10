"""Tests for deterministic world generation and network constraints."""

import time

import networkx as nx

from phantom_veil.worldgen import generate_world


def test_deterministic_generation():
    """Verify that using the same seed produces identical outputs."""
    seed = 42
    nodes1, edges1, demands1, bottles1 = generate_world(seed)
    nodes2, edges2, demands2, bottles2 = generate_world(seed)

    assert nodes1.equals(nodes2)
    assert edges1.equals(edges2)
    assert demands1.equals(demands2)
    assert bottles1.equals(bottles2)


def test_different_seeds_diverge():
    """Verify that different seeds produce different graphs and attributes."""
    nodes1, edges1, demands1, _ = generate_world(42)
    nodes2, edges2, demands2, _ = generate_world(100)

    # They should not be identical
    assert not (nodes1.equals(nodes2) and edges1.equals(edges2))


def test_node_properties_and_tiers():
    """Verify nodes distribution across tiers and positive capacity."""
    nodes, _, _, _ = generate_world(42, node_count=50)

    assert len(nodes) == 50
    assert (nodes["capacity"] > 0).all()
    assert set(nodes["tier"]) == {1, 2, 3, 4}

    # Verify distribution
    # T1: 10% of 50 = 5
    # T2: 20% of 50 = 10
    # T3: 30% of 50 = 15
    # T4: rest = 20
    assert len(nodes[nodes["tier"] == 1]) == 5
    assert len(nodes[nodes["tier"] == 2]) == 10
    assert len(nodes[nodes["tier"] == 3]) == 15
    assert len(nodes[nodes["tier"] == 4]) == 20


def test_connectivity_t4_to_t1():
    """Verify at least one path from Tier-4 nodes to Tier-1 nodes."""
    nodes, edges, _, _ = generate_world(42)

    graph = nx.DiGraph()
    graph.add_nodes_from(nodes["node_id"])
    for _, row in edges.iterrows():
        graph.add_edge(row["source"], row["target"])

    t1_nodes = nodes[nodes["tier"] == 1]["node_id"].tolist()
    t4_nodes = nodes[nodes["tier"] == 4]["node_id"].tolist()

    has_path = False
    for t4 in t4_nodes:
        for t1 in t1_nodes:
            if nx.has_path(graph, t4, t1):
                has_path = True
                break
        if has_path:
            break

    assert has_path, "No path found from any Tier-4 node to any Tier-1 SKU"


def test_no_bottleneck_leakage():
    """Verify that the public nodes DataFrame does not contain hidden bottleneck info."""
    nodes, _, _, bottles = generate_world(42)

    assert "is_hidden_bottleneck" not in nodes.columns
    assert "true_capacity" not in nodes.columns

    # Verify bottleneck is marked in internal DataFrame
    assert "is_hidden_bottleneck" in bottles.columns
    assert "true_capacity" in bottles.columns
    assert bottles["is_hidden_bottleneck"].any()


def test_generation_speed():
    """Verify that generating a default 50-node world is fast."""
    start_time = time.perf_counter()
    generate_world(123, node_count=50)
    duration = time.perf_counter() - start_time

    # Must complete under 100ms
    assert duration < 0.10
