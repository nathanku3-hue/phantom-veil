"""Deterministic synthetic supply-chain world generator for Phantom Veil."""

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from phantom_veil.models import GEOGRAPHIC_REGIONS, PROCESS_CLASSES, RESOURCE_CLASSES


def generate_world(
    seed: int, node_count: int = 50, horizon_weeks: int = 52
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate a deterministic synthetic supply-chain network.

    Args:
        seed: Random seed for determinism.
        node_count: Total number of nodes (default 50).
        horizon_weeks: Planning horizon in weeks (default 52).

    Returns:
        nodes_df: Public observed nodes DataFrame.
        edges_df: Edges/BOM relationships DataFrame.
        demands_df: Weekly demands for Tier-1 SKUs.
        internal_bottlenecks: Ground-truth bottleneck and true capacities.
    """
    rng = np.random.default_rng(seed)

    # Distribute nodes across Tiers 1-4
    tier_counts = _distribute_tiers(node_count)

    # Generate Nodes and internal bottleneck labels
    nodes_data, bottlenecks_data = _generate_nodes(rng, tier_counts)

    nodes_df = pd.DataFrame(nodes_data)
    bottlenecks_df = pd.DataFrame(bottlenecks_data)

    # Group node IDs by tier for edge generation
    tier_nodes: Dict[int, List[str]] = {t: [] for t in range(1, 5)}
    for node in nodes_data:
        tier_nodes[node["tier"]].append(node["node_id"])

    # Generate Edges ensuring connection paths from Tier 4 to Tier 1
    edges_data = _generate_edges(rng, tier_nodes)
    edges_df = pd.DataFrame(edges_data)

    # Generate Demands for Tier-1 nodes
    demands_data = _generate_demands(rng, tier_nodes[1], horizon_weeks)
    demands_df = pd.DataFrame(demands_data)

    return nodes_df, edges_df, demands_df, bottlenecks_df


def _distribute_tiers(node_count: int) -> Dict[int, int]:
    """Distribute node count across Tiers 1 to 4."""
    if node_count < 4:
        raise ValueError("node_count must be at least 4 to cover Tiers 1-4")

    t1 = max(1, int(node_count * 0.10))
    t2 = max(1, int(node_count * 0.20))
    t3 = max(1, int(node_count * 0.30))
    t4 = node_count - (t1 + t2 + t3)

    return {1: t1, 2: t2, 3: t3, 4: t4}


def _generate_nodes(
    rng: np.random.Generator, tier_counts: Dict[int, int]
) -> Tuple[List[dict], List[dict]]:
    """Generate node records and corresponding private bottleneck ground-truth."""
    nodes = []
    bottlenecks = []
    node_id_counter = 1

    # Predetermine which nodes in T3 and T4 will be hidden bottlenecks
    # We will pick 1 node in Tier 3 and 1 node in Tier 4
    for tier, count in tier_counts.items():
        # Select bottleneck index for Tier 3 and 4
        bottleneck_idx = -1
        if tier in (3, 4) and count > 0:
            bottleneck_idx = rng.integers(0, count)

        for i in range(count):
            node_id = f"N_{node_id_counter:03d}"
            node_id_counter += 1

            # Capacity must be positive
            nominal_capacity = float(rng.uniform(500.0, 2000.0))
            nominal_capacity = round(nominal_capacity, 2)

            is_bottleneck = i == bottleneck_idx
            true_capacity = nominal_capacity
            if is_bottleneck:
                # 5x constraint: true capacity is 20% of nominal capacity
                true_capacity = round(nominal_capacity * 0.20, 2)

            nodes.append(
                {
                    "node_id": node_id,
                    "tier": tier,
                    "capacity": nominal_capacity,
                    "process_class": PROCESS_CLASSES[tier],
                    "resource_class": RESOURCE_CLASSES[tier],
                    "geographic_region": rng.choice(GEOGRAPHIC_REGIONS),
                }
            )

            bottlenecks.append(
                {
                    "node_id": node_id,
                    "is_hidden_bottleneck": is_bottleneck,
                    "true_capacity": true_capacity,
                }
            )

    return nodes, bottlenecks


def _generate_edges(rng: np.random.Generator, tier_nodes: Dict[int, List[str]]) -> List[dict]:
    """Generate edges between adjacent tiers ensuring a complete path."""
    edges = []
    edges_set = set()

    # Step 1: Connect T -> T+1 (Downstream to Upstream selection)
    # Ensure every node at Tier T (1, 2, 3) has 1 to 2 parent nodes at Tier T+1
    for tier in range(1, 4):
        downstream_nodes = tier_nodes[tier]
        upstream_nodes = tier_nodes[tier + 1]

        for down_node in downstream_nodes:
            # Pick 1 to 2 parents
            parent_count = min(len(upstream_nodes), rng.integers(1, 3))
            parents = rng.choice(upstream_nodes, size=parent_count, replace=False)

            for parent in parents:
                _add_edge_if_new(edges, edges_set, rng, parent, down_node)

    # Step 2: Fix orphan upstream nodes to guarantee every node has a path
    # Ensure every node at Tier T+1 (2, 3, 4) has at least one child at Tier T
    for tier in range(1, 4):
        downstream_nodes = tier_nodes[tier]
        upstream_nodes = tier_nodes[tier + 1]

        # Find which upstream nodes have no children in our current edge set
        active_sources = {e["source"] for e in edges}
        orphans = [node for node in upstream_nodes if node not in active_sources]

        for orphan in orphans:
            # Connect to a random downstream child
            child = rng.choice(downstream_nodes)
            _add_edge_if_new(edges, edges_set, rng, orphan, child)

    return edges


def _add_edge_if_new(
    edges: List[dict], edges_set: set, rng: np.random.Generator, source: str, target: str
) -> None:
    """Helper to append an edge with properties if not already present."""
    edge_key = (source, target)
    if edge_key not in edges_set:
        edges_set.add(edge_key)
        edges.append(
            {
                "source": source,
                "target": target,
                "bom_ratio": round(float(rng.uniform(0.5, 2.0)), 2),
                "transit_delay_weeks": int(rng.integers(1, 4)),
            }
        )


def _generate_demands(
    rng: np.random.Generator, tier_1_nodes: List[str], horizon_weeks: int
) -> List[dict]:
    """Generate weekly SKU demands with a demand shock period."""
    demands = []

    # Choose a baseline and shock window for each SKU
    for sku in tier_1_nodes:
        baseline = float(rng.uniform(50.0, 150.0))

        # Random shock interval between week 20 and 40
        shock_start = int(rng.integers(20, 35))
        shock_duration = int(rng.integers(4, 9))
        shock_end = shock_start + shock_duration
        shock_factor = float(rng.uniform(3.0, 5.0))

        for week in range(1, horizon_weeks + 1):
            qty = baseline
            if shock_start <= week < shock_end:
                qty *= shock_factor

            # Add minor noise (non-negative)
            qty += float(rng.uniform(-5.0, 5.0))
            qty = round(max(1.0, qty), 2)

            demands.append({"sku_id": sku, "week": week, "quantity": qty})

    return demands
