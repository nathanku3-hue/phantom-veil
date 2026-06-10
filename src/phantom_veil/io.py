"""Input/Output operations and schema validations for Phantom Veil."""

import os
from typing import Tuple

import networkx as nx
import pandas as pd


def validate_nodes(df: pd.DataFrame) -> None:
    """Validate schema and contents of the nodes DataFrame."""
    required_cols = [
        "node_id",
        "tier",
        "capacity",
        "process_class",
        "resource_class",
        "geographic_region",
    ]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column in nodes schema: {col}")

    # Validate tiers
    if not df["tier"].isin([1, 2, 3, 4]).all():
        raise ValueError("Node tiers must be integers in [1, 2, 3, 4]")

    # Validate positive capacities
    if (df["capacity"] <= 0).any():
        raise ValueError("Node capacity must be strictly positive")

    # Validate that no hidden bottleneck leak occurred
    leak_cols = ["is_hidden_bottleneck", "true_capacity"]
    for col in leak_cols:
        if col in df.columns:
            raise ValueError(
                f"Security leak: Hidden bottleneck column '{col}' exposed in public view"
            )


def validate_edges(df: pd.DataFrame, nodes_df: pd.DataFrame = None) -> None:
    """Validate schema and contents of the edges DataFrame."""
    required_cols = ["source", "target", "bom_ratio", "transit_delay_weeks"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column in edges schema: {col}")

    # Validate positive BOM ratios
    if (df["bom_ratio"] <= 0).any():
        raise ValueError("Edge bom_ratio must be strictly positive")

    # Validate non-negative transit delays
    if (df["transit_delay_weeks"] < 0).any():
        raise ValueError("Edge transit_delay_weeks must be non-negative")

    # If nodes_df is provided, validate endpoints exist
    if nodes_df is not None:
        valid_nodes = set(nodes_df["node_id"])
        invalid_sources = df[~df["source"].isin(valid_nodes)]
        if not invalid_sources.empty:
            raise ValueError(
                f"Edge source node(s) do not exist: {invalid_sources['source'].tolist()}"
            )
        invalid_targets = df[~df["target"].isin(valid_nodes)]
        if not invalid_targets.empty:
            raise ValueError(
                f"Edge target node(s) do not exist: {invalid_targets['target'].tolist()}"
            )


def validate_demands(df: pd.DataFrame, nodes_df: pd.DataFrame = None) -> None:
    """Validate schema and contents of the demands DataFrame."""
    required_cols = ["sku_id", "week", "quantity"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column in demands schema: {col}")

    # Validate weeks
    if (df["week"] <= 0).any():
        raise ValueError("Demand week must be positive")

    # Validate non-negative quantities
    if (df["quantity"] < 0).any():
        raise ValueError("Demand quantity must be non-negative")

    # Validate SKU node exists and is Tier 1
    if nodes_df is not None:
        tier_1_nodes = set(nodes_df[nodes_df["tier"] == 1]["node_id"])
        invalid_skus = df[~df["sku_id"].isin(tier_1_nodes)]
        if not invalid_skus.empty:
            raise ValueError(
                f"Demand sku_id must exist as Tier-1 node: {invalid_skus['sku_id'].tolist()}"
            )


def validate_path_t4_to_t1(nodes_df: pd.DataFrame, edges_df: pd.DataFrame) -> None:
    """Ensure at least one terminal Tier-1 SKU has a path to Tier-4 sources."""
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes_df["node_id"])
    for _, row in edges_df.iterrows():
        graph.add_edge(row["source"], row["target"])

    t1_nodes = nodes_df[nodes_df["tier"] == 1]["node_id"].tolist()
    t4_nodes = nodes_df[nodes_df["tier"] == 4]["node_id"].tolist()

    has_path = False
    for t4 in t4_nodes:
        for t1 in t1_nodes:
            if nx.has_path(graph, t4, t1):
                has_path = True
                break
        if has_path:
            break

    if not has_path:
        raise ValueError("At least one Tier-1 SKU must be reachable from a Tier-4 source node")


def save_world(
    directory: str, nodes: pd.DataFrame, edges: pd.DataFrame, demands: pd.DataFrame
) -> None:
    """Validate and save world datasets to CSV in the target directory."""
    validate_nodes(nodes)
    validate_edges(edges, nodes)
    validate_demands(demands, nodes)
    validate_path_t4_to_t1(nodes, edges)

    os.makedirs(directory, exist_ok=True)
    nodes.to_csv(os.path.join(directory, "nodes.csv"), index=False)
    edges.to_csv(os.path.join(directory, "edges.csv"), index=False)
    demands.to_csv(os.path.join(directory, "demands.csv"), index=False)


def load_world(directory: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load and validate world datasets from CSV in the target directory."""
    nodes = pd.read_csv(os.path.join(directory, "nodes.csv"))
    edges = pd.read_csv(os.path.join(directory, "edges.csv"))
    demands = pd.read_csv(os.path.join(directory, "demands.csv"))

    validate_nodes(nodes)
    validate_edges(edges, nodes)
    validate_demands(demands, nodes)
    validate_path_t4_to_t1(nodes, edges)

    return nodes, edges, demands
