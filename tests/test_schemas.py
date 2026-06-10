"""Tests for nodes, edges, and demands schema validations."""

import pandas as pd
import pytest

from phantom_veil.io import (
    validate_demands,
    validate_edges,
    validate_nodes,
    validate_path_t4_to_t1,
)


@pytest.fixture
def valid_data():
    """Return valid nodes, edges, and demands dataframes."""
    nodes = pd.DataFrame(
        [
            {
                "node_id": "T1_N1",
                "tier": 1,
                "capacity": 100.0,
                "process_class": "final_assembly",
                "resource_class": "module",
                "geographic_region": "Taiwan",
            },
            {
                "node_id": "T4_N1",
                "tier": 4,
                "capacity": 500.0,
                "process_class": "chemical_synthesis",
                "resource_class": "gas_chemical",
                "geographic_region": "US",
            },
        ]
    )

    edges = pd.DataFrame(
        [
            {
                "source": "T4_N1",
                "target": "T1_N1",
                "bom_ratio": 1.5,
                "transit_delay_weeks": 2,
            }
        ]
    )

    demands = pd.DataFrame([{"sku_id": "T1_N1", "week": 1, "quantity": 50.0}])

    return nodes, edges, demands


def test_valid_schemas_pass(valid_data):
    """Verify that correct schemas validate without raising errors."""
    nodes, edges, demands = valid_data
    validate_nodes(nodes)
    validate_edges(edges, nodes)
    validate_demands(demands, nodes)
    validate_path_t4_to_t1(nodes, edges)


def test_nodes_missing_columns(valid_data):
    """Verify that missing columns trigger a ValueError."""
    nodes, _, _ = valid_data
    invalid_nodes = nodes.drop(columns=["capacity"])
    with pytest.raises(ValueError, match="Missing required column in nodes schema"):
        validate_nodes(invalid_nodes)


def test_nodes_invalid_tier(valid_data):
    """Verify that invalid tiers trigger a ValueError."""
    nodes, _, _ = valid_data
    invalid_nodes = nodes.copy()
    invalid_nodes.loc[0, "tier"] = 5
    with pytest.raises(ValueError, match="Node tiers must be integers in"):
        validate_nodes(invalid_nodes)


def test_nodes_negative_capacity(valid_data):
    """Verify that negative capacity values trigger a ValueError."""
    nodes, _, _ = valid_data
    invalid_nodes = nodes.copy()
    invalid_nodes.loc[0, "capacity"] = -10.0
    with pytest.raises(ValueError, match="Node capacity must be strictly positive"):
        validate_nodes(invalid_nodes)


def test_nodes_hidden_leak(valid_data):
    """Verify that leaking hidden labels triggers a ValueError."""
    nodes, _, _ = valid_data
    invalid_nodes = nodes.copy()
    invalid_nodes["is_hidden_bottleneck"] = False
    with pytest.raises(ValueError, match="Security leak: Hidden bottleneck column"):
        validate_nodes(invalid_nodes)


def test_edges_negative_bom(valid_data):
    """Verify that negative BOM ratios trigger a ValueError."""
    nodes, edges, _ = valid_data
    invalid_edges = edges.copy()
    invalid_edges.loc[0, "bom_ratio"] = 0.0
    with pytest.raises(ValueError, match="Edge bom_ratio must be strictly positive"):
        validate_edges(invalid_edges, nodes)


def test_edges_negative_delay(valid_data):
    """Verify that negative transit delays trigger a ValueError."""
    nodes, edges, _ = valid_data
    invalid_edges = edges.copy()
    invalid_edges.loc[0, "transit_delay_weeks"] = -1
    with pytest.raises(ValueError, match="Edge transit_delay_weeks must be non-negative"):
        validate_edges(invalid_edges, nodes)


def test_edges_missing_endpoints(valid_data):
    """Verify that missing edge endpoint nodes trigger a ValueError."""
    nodes, edges, _ = valid_data
    invalid_edges = edges.copy()
    invalid_edges.loc[0, "source"] = "NON_EXISTENT"
    with pytest.raises(ValueError, match="Edge source node\\(s\\) do not exist"):
        validate_edges(invalid_edges, nodes)


def test_demands_invalid_sku(valid_data):
    """Verify that demands for non-existent or non-Tier-1 SKUs fail validation."""
    nodes, _, demands = valid_data
    invalid_demands = demands.copy()
    # T4_N1 is Tier 4, not Tier 1 SKU
    invalid_demands.loc[0, "sku_id"] = "T4_N1"
    with pytest.raises(ValueError, match="Demand sku_id must exist as Tier-1 node"):
        validate_demands(invalid_demands, nodes)


def test_demands_negative_quantity(valid_data):
    """Verify that negative demand quantities fail validation."""
    nodes, _, demands = valid_data
    invalid_demands = demands.copy()
    invalid_demands.loc[0, "quantity"] = -1.0
    with pytest.raises(ValueError, match="Demand quantity must be non-negative"):
        validate_demands(invalid_demands, nodes)


def test_no_path_t4_to_t1():
    """Verify that validation fails if no path exists from Tier 4 to Tier 1."""
    nodes = pd.DataFrame(
        [
            {
                "node_id": "T1_N1",
                "tier": 1,
                "capacity": 100.0,
                "process_class": "final_assembly",
                "resource_class": "module",
                "geographic_region": "Taiwan",
            },
            {
                "node_id": "T4_N1",
                "tier": 4,
                "capacity": 500.0,
                "process_class": "chemical_synthesis",
                "resource_class": "gas_chemical",
                "geographic_region": "US",
            },
        ]
    )
    # No edges at all
    edges = pd.DataFrame(columns=["source", "target", "bom_ratio", "transit_delay_weeks"])
    with pytest.raises(ValueError, match="At least one Tier-1 SKU must be reachable"):
        validate_path_t4_to_t1(nodes, edges)
