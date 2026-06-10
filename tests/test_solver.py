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


def test_capacity_shadow_price_mapping_after_week_one():
    """Prove that week-2-or-later capacity marginals are extracted from true capacity rows."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)
    res = solve_shortage_lp(nodes, edges, demands)

    metadata = res.raw_solver_metadata
    assert "capacity_constraint_rows" in metadata
    assert "inequality_rows_per_week" in metadata
    assert "row_counts" in metadata

    row_counts = metadata["row_counts"]
    assert row_counts["capacity"] == len(nodes) * 5
    assert row_counts["flow_conservation"] == len(nodes) * 5

    capacity_rows = metadata["capacity_constraint_rows"]
    week_2_or_later = [r for r in capacity_rows if r["week"] >= 2]
    assert len(week_2_or_later) > 0

    N = len(nodes)
    E = len(edges)
    W = 5
    t1_nodes = nodes[nodes["tier"] == 1]["node_id"].tolist()
    S = len(t1_nodes)

    node_id_to_idx = {row["node_id"]: idx for idx, row in nodes.iterrows()}
    sku_to_idx = {node_id: idx for idx, node_id in enumerate(t1_nodes)}

    from phantom_veil.solver import _build_lp_matrices, _var_index

    c, A_ub, b_ub, A_eq, b_eq, _, _, _ = _build_lp_matrices(
        nodes, edges, demands, N, E, S, W, node_id_to_idx, sku_to_idx, t1_nodes
    )

    A_ub_csr = A_ub.tocsr()

    for entry in week_2_or_later:
        row_idx = entry["row_idx"]
        node_id = entry["node_id"]
        week = entry["week"]

        node_idx = node_id_to_idx[node_id]
        expected_var_idx = _var_index("production", node_idx, week - 1, N, E, S)

        row_data = A_ub_csr.getrow(row_idx)
        non_zero_cols = row_data.indices
        non_zero_vals = row_data.data

        # Capacity rows are not confused with flow-conservation, BOM/input, or served-limit rows.
        # Capacity row must have exactly 1 non-zero entry, which is 1.0 at expected_var_idx.
        assert len(non_zero_cols) == 1
        assert non_zero_cols[0] == expected_var_idx
        assert np.isclose(non_zero_vals[0], 1.0)


def test_later_week_finite_difference_shadow_price():
    """Verify that changing a later-week bottleneck capacity produces objective movement.

    Consistent with raw_marginal * epsilon.
    """
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
            {"sku_id": "T1_SKU", "week": 3, "quantity": 100.0},
        ]
    )

    res_base = solve_shortage_lp(nodes, edges, demands)
    assert res_base.success is True

    # Retrieve T4_SRC capacity shadow price at week 2
    t4_week_2_price = res_base.capacity_shadow_prices[
        (res_base.capacity_shadow_prices["node_id"] == "T4_SRC")
        & (res_base.capacity_shadow_prices["week"] == 2)
    ].iloc[0]

    raw_marg = t4_week_2_price["raw_marginal"]
    # Shadow value should be positive, meaning raw_marginal is negative
    assert raw_marg < -0.1
    assert t4_week_2_price["capacity_shadow_value"] > 0.1

    # Rebuild matrices
    N = len(nodes)
    E = len(edges)
    W = 3
    t1_nodes = nodes[nodes["tier"] == 1]["node_id"].tolist()
    S = len(t1_nodes)

    node_id_to_idx = {row["node_id"]: idx for idx, row in nodes.iterrows()}
    sku_to_idx = {node_id: idx for idx, node_id in enumerate(t1_nodes)}

    from phantom_veil.solver import _build_lp_matrices

    c, A_ub, b_ub, A_eq, b_eq, row_map, _, _ = _build_lp_matrices(
        nodes, edges, demands, N, E, S, W, node_id_to_idx, sku_to_idx, t1_nodes
    )

    # Find the row index of T4_SRC in week 2
    row_idx = [r["row_idx"] for r in row_map if r["node_id"] == "T4_SRC" and r["week"] == 2][0]

    # Verify that changing only the week 2 constraint RHS produces the expected difference
    epsilon = 0.2
    b_ub_perturbed = b_ub.copy()
    b_ub_perturbed[row_idx] += epsilon

    # Solve base with scipy directly using rebuilt matrices to verify consistency
    V = W * (N + E + 2 * S)
    bounds = [(0.0, None) for _ in range(V)]

    import scipy.optimize as opt

    res_direct_base = opt.linprog(
        c=c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs"
    )
    res_direct_perturbed = opt.linprog(
        c=c,
        A_ub=A_ub,
        b_ub=b_ub_perturbed,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )

    expected_diff = raw_marg * epsilon
    actual_diff = res_direct_perturbed.fun - res_direct_base.fun

    assert np.isclose(actual_diff, expected_diff, atol=1e-4)
