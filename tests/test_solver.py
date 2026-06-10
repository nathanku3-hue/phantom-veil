"""Tests for the time-expanded LP shortage solver and shadow pricing contract."""

import time

import numpy as np
import pandas as pd
import pytest

from phantom_veil.solver import solve_shortage_lp
from phantom_veil.worldgen import generate_world


def test_lp_solves_default_generated_world():
    """Verify that a default generated world is solved successfully."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=50, horizon_weeks=52)
    res = solve_shortage_lp(nodes, edges, demands)

    assert res.success is True
    assert res.status == 0
    assert res.objective_value >= 0.0


def test_lp_result_has_expected_tables():
    """Verify that the typed result object contains the correct tables and columns."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)
    res = solve_shortage_lp(nodes, edges, demands)

    # Check served_demand schema
    assert isinstance(res.served_demand, pd.DataFrame)
    assert set(res.served_demand.columns) == {"sku_id", "week", "quantity"}

    # Check shortages schema
    assert isinstance(res.shortages, pd.DataFrame)
    assert set(res.shortages.columns) == {"sku_id", "week", "quantity"}

    # Check capacity_shadow_prices schema
    assert isinstance(res.capacity_shadow_prices, pd.DataFrame)
    assert set(res.capacity_shadow_prices.columns) == {
        "node_id",
        "week",
        "raw_marginal",
        "capacity_shadow_value",
    }


def test_shortage_is_nonnegative():
    """Verify that all shortages are non-negative and served quantities are non-negative."""
    nodes, edges, demands, _ = generate_world(seed=123, node_count=12, horizon_weeks=8)
    res = solve_shortage_lp(nodes, edges, demands)

    assert (res.shortages["quantity"] >= -1e-6).all()
    assert (res.served_demand["quantity"] >= -1e-6).all()


def test_capacity_shadow_prices_are_returned():
    """Verify shadow prices properties and non-negativity of business shadow values."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)
    res = solve_shortage_lp(nodes, edges, demands)

    prices = res.capacity_shadow_prices
    assert len(prices) == len(nodes) * 5

    # capacity_shadow_value = -raw_marginal.
    # Highs returned marginals for <= capacity constraint are <= 0 (objective improvement).
    # Thus shadow value should be >= 0.
    assert (prices["capacity_shadow_value"] >= -1e-6).all()
    assert (prices["raw_marginal"] <= 1e-6).all()


def test_solver_rejects_invalid_schema():
    """Verify that the solver fails validation if invalid inputs are supplied."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    # Negative capacity node
    invalid_nodes = nodes.copy()
    invalid_nodes.loc[0, "capacity"] = -5.0

    with pytest.raises(ValueError, match="Node capacity must be strictly positive"):
        solve_shortage_lp(invalid_nodes, edges, demands)


def test_solver_does_not_require_hidden_bottleneck_labels():
    """Verify that public view (lacking bottleneck tags) is sufficient for the solver."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    # Exclude any hidden columns (they should be already excluded in generate_world)
    assert "is_hidden_bottleneck" not in nodes.columns
    assert "true_capacity" not in nodes.columns

    res = solve_shortage_lp(nodes, edges, demands)
    assert res.success is True


def test_solver_runtime_default_world_is_reasonable():
    """Verify that a standard 50-node 52-week world is solved under 3 seconds."""
    nodes, edges, demands, _ = generate_world(seed=99, node_count=50, horizon_weeks=52)

    start = time.perf_counter()
    res = solve_shortage_lp(nodes, edges, demands)
    duration = time.perf_counter() - start

    assert res.success is True
    assert duration < 3.0


def test_shadow_price_sign_and_finite_difference():
    """Validate sign convention and marginal pricing using a handcrafted case."""
    # Handcrafted case where demand exceeds bottleneck capacity.
    # T4_SRC has capacity 10, BOM ratio is 2.0 to target T1_SKU.
    # Therefore, T1_SKU production is constrained to 10 / 2.0 = 5 units.
    # Demand is 100. Shortage will be 95 units.
    nodes = pd.DataFrame(
        [
            {
                "node_id": "T1_SKU",
                "tier": 1,
                "capacity": 1000.0,
                "process_class": "final_assembly",
                "resource_class": "module",
                "geographic_region": "Taiwan",
            },
            {
                "node_id": "T4_SRC",
                "tier": 4,
                "capacity": 10.0,
                "process_class": "chemical_synthesis",
                "resource_class": "gas_chemical",
                "geographic_region": "US",
            },
        ]
    )

    edges = pd.DataFrame(
        [
            {
                "source": "T4_SRC",
                "target": "T1_SKU",
                "bom_ratio": 2.0,
                "transit_delay_weeks": 1,
            }
        ]
    )

    demands = pd.DataFrame(
        [
            {"sku_id": "T1_SKU", "week": 1, "quantity": 0.0},
            {"sku_id": "T1_SKU", "week": 2, "quantity": 100.0},
        ]
    )

    # Solve baseline
    res_base = solve_shortage_lp(nodes, edges, demands)
    assert res_base.success is True

    # Retrieve T4_SRC capacity shadow price at week 1
    # Note: transit_delay is 1, so week 2 production at SKU uses week 1 flow from SRC.
    t4_week_1_price = res_base.capacity_shadow_prices[
        (res_base.capacity_shadow_prices["node_id"] == "T4_SRC")
        & (res_base.capacity_shadow_prices["week"] == 1)
    ].iloc[0]

    raw_marg = t4_week_1_price["raw_marginal"]
    shadow_val = t4_week_1_price["capacity_shadow_value"]

    # Raw marginal should be negative (as objective shortage drops by adding capacity),
    # meaning the shadow value (capacity_shadow_value = -raw_marginal) is positive.
    assert raw_marg < -0.1
    assert shadow_val > 0.1

    # Finite-Difference Verification: Increase bottleneck capacity by epsilon
    epsilon = 0.2
    nodes_perturbed = nodes.copy()
    nodes_perturbed.loc[nodes_perturbed["node_id"] == "T4_SRC", "capacity"] = 10.0 + epsilon

    res_perturbed = solve_shortage_lp(nodes_perturbed, edges, demands)
    assert res_perturbed.success is True

    # Validate difference:
    # Objective value represents total shortage.
    # Shortage drops from 95 to 95 - (epsilon / 2.0) = 94.9.
    # Expected objective change is raw_marginal * epsilon.
    expected_diff = raw_marg * epsilon
    actual_diff = res_perturbed.objective_value - res_base.objective_value

    assert np.isclose(actual_diff, expected_diff, atol=1e-4)
