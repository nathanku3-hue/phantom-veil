"""Tests for the Scenario Perturbation and Intervention Runner (MVP-004)."""

import pandas as pd
import pytest

from phantom_veil.scenarios import (
    ScenarioSpec,
    apply_scenario,
    compare_scenarios,
    evaluate_intervention_set,
    run_scenario,
)
from phantom_veil.worldgen import generate_world


def test_apply_scenario_no_mutation():
    """Verify that apply_scenario does not mutate input DataFrames in place."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    nodes_orig = nodes.copy()
    edges_orig = edges.copy()
    demands_orig = demands.copy()

    spec = ScenarioSpec(
        scenario_id="shock_test",
        demand_multiplier=2.0,
        capacity_multiplier_by_node={nodes.iloc[0]["node_id"]: 0.5},
        delay_delta_by_edge={(edges.iloc[0]["source"], edges.iloc[0]["target"]): 2},
        intervention_capacity_add_by_node={nodes.iloc[0]["node_id"]: 10.0},
        weeks=[2, 3],
    )

    new_nodes, new_edges, new_demands = apply_scenario(nodes, edges, demands, spec)

    # Check original DataFrames are identical to before
    pd.testing.assert_frame_equal(nodes, nodes_orig)
    pd.testing.assert_frame_equal(edges, edges_orig)
    pd.testing.assert_frame_equal(demands, demands_orig)

    # Check that modifications were applied to copies
    expected_cap = round(float(nodes.iloc[0]["capacity"] * 0.5 + 10.0), 4)
    assert new_nodes.iloc[0]["capacity"] == expected_cap


def test_demand_shock():
    """Verify that demand multiplier applies only to the specified weeks."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    spec = ScenarioSpec(
        scenario_id="demand_shock",
        demand_multiplier=3.0,
        weeks=[2, 4],
    )

    _, _, new_demands = apply_scenario(nodes, edges, demands, spec)

    # Compare week by week
    for w in range(1, 6):
        orig_w = demands[demands["week"] == w]["quantity"].sum()
        new_w = new_demands[new_demands["week"] == w]["quantity"].sum()
        if w in [2, 4]:
            assert pytest.approx(new_w) == orig_w * 3.0
        else:
            assert pytest.approx(new_w) == orig_w


def test_capacity_shock_and_intervention():
    """Verify capacity multiplier and intervention additions."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    n_id = nodes.iloc[0]["node_id"]
    spec = ScenarioSpec(
        scenario_id="capacity_shock",
        capacity_multiplier_by_node={n_id: 0.1},
        intervention_capacity_add_by_node={n_id: 50.0},
    )

    new_nodes, _, _ = apply_scenario(nodes, edges, demands, spec)

    orig_cap = nodes.iloc[0]["capacity"]
    new_cap = new_nodes.iloc[0]["capacity"]
    assert pytest.approx(new_cap) == round(orig_cap * 0.1 + 50.0, 4)


def test_delay_shock():
    """Verify transit delay delta application."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    src = edges.iloc[0]["source"]
    tgt = edges.iloc[0]["target"]
    orig_delay = edges.iloc[0]["transit_delay_weeks"]

    spec = ScenarioSpec(
        scenario_id="delay_shock",
        delay_delta_by_edge={(src, tgt): 3},
    )

    _, new_edges, _ = apply_scenario(nodes, edges, demands, spec)

    new_delay = new_edges.iloc[0]["transit_delay_weeks"]
    assert new_delay == orig_delay + 3


def test_run_and_compare_scenarios():
    """Verify run_scenario and compare_scenarios run successfully and output expected fields."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    spec_base = ScenarioSpec(scenario_id="base")
    spec_perturbed = ScenarioSpec(
        scenario_id="perturbed",
        demand_multiplier=1.5,
        weeks=[1, 2, 3, 4, 5],
    )

    res_base = run_scenario(nodes, edges, demands, spec_base)
    res_perturbed = run_scenario(nodes, edges, demands, spec_perturbed)

    assert res_base.total_shortage >= 0.0
    assert len(res_base.top_shadow_price_nodes) <= len(nodes)
    assert len(res_base.weekly_shortages) == 5

    diff = compare_scenarios(res_base, res_perturbed, top_k=3)
    assert "objective_delta" in diff
    assert "total_shortage_delta" in diff
    assert "shortage_reduction" in diff
    assert "top_k_bottleneck_rank_changes" in diff

    # Perturbed scenario has 1.5x demand, so shortage should be >= baseline
    assert diff["total_shortage_delta"] >= -1e-6


def test_evaluate_intervention_set():
    """Verify evaluate_intervention_set logic and metrics."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=10, horizon_weeks=5)

    metrics = evaluate_intervention_set(nodes, edges, demands, top_k=2, capacity_increment=100.0)

    assert "baseline_shortage" in metrics
    assert "intervention_shortage" in metrics
    assert "shortage_reduction" in metrics
    assert "total_capacity_added" in metrics
    assert "reduction_per_unit_capacity" in metrics

    assert metrics["total_capacity_added"] == 200.0
    assert metrics["shortage_reduction"] >= 0.0
    assert metrics["reduction_per_unit_capacity"] >= 0.0
