"""Tests for the Private Coordination ADMM Smoke Layer (MVP-008)."""

import pandas as pd

import phantom_veil
from phantom_veil.benchmark import rank_bottlenecks_by_shadow_price
from phantom_veil.coordination import (
    CoordinationConfig,
    evaluate_coordination_benefits,
    run_admm_coordination_smoke,
    select_coordination_targets,
)
from phantom_veil.solver import solve_shortage_lp
from phantom_veil.worldgen import generate_world


def test_coordination_targeting_and_no_leakage():
    """Verify target selection and lack of private information leakage."""
    nodes = pd.DataFrame(
        [
            {"node_id": "N1", "capacity": 50},
            {"node_id": "N2", "capacity": 50},
            {"node_id": "N3", "capacity": 50},
        ]
    )

    public_ranking = ["N1", "N2", "N3"]
    targets = select_coordination_targets(public_ranking, top_k=2)
    assert targets == ["N1", "N2"]

    features = {
        "N1": {"shadow_price": 5.0, "shortage_delta": 20.0},
        "N2": {"shadow_price": 2.0, "shortage_delta": 5.0},
    }

    config = CoordinationConfig(max_iterations=10, capacity_step_limit=50.0)
    res = run_admm_coordination_smoke(nodes, targets, features, config)

    assert res.recommended_capacity_add_by_node is not None
    assert set(res.recommended_capacity_add_by_node.keys()) == {"N1", "N2"}

    # No leakage check: ensure cost tables c_n or benefits d_n are not exposed
    assert not hasattr(res, "c")
    assert not hasattr(res, "d")


def test_coordination_determinism_and_step_limits():
    """Verify ADMM runs deterministically and respects step limits."""
    nodes = pd.DataFrame(
        [
            {"node_id": "N1", "capacity": 100},
            {"node_id": "N2", "capacity": 100},
        ]
    )
    features = {
        "N1": {"shadow_price": 10.0, "shortage_delta": 100.0},
        "N2": {"shadow_price": 5.0, "shortage_delta": 50.0},
    }

    config = CoordinationConfig(max_iterations=50, capacity_step_limit=30.0)

    res1 = run_admm_coordination_smoke(nodes, ["N1", "N2"], features, config)
    res2 = run_admm_coordination_smoke(nodes, ["N1", "N2"], features, config)

    assert res1.recommended_capacity_add_by_node == res2.recommended_capacity_add_by_node
    assert res1.consensus_residuals == res2.consensus_residuals
    assert res1.objective_trace == res2.objective_trace

    for nid, val in res1.recommended_capacity_add_by_node.items():
        assert val >= 0.0
        assert val <= config.capacity_step_limit


def test_coordination_residuals_convergence():
    """Verify that ADMM residuals converge or remain bounded."""
    nodes = pd.DataFrame(
        [
            {"node_id": "N1", "capacity": 100},
            {"node_id": "N2", "capacity": 100},
        ]
    )
    features = {
        "N1": {"shadow_price": 10.0, "shortage_delta": 100.0},
        "N2": {"shadow_price": 5.0, "shortage_delta": 50.0},
    }

    config = CoordinationConfig(max_iterations=100, tolerance=1e-4, rho=1.0)
    res = run_admm_coordination_smoke(nodes, ["N1", "N2"], features, config)

    assert len(res.consensus_residuals) > 0
    assert res.consensus_residuals[-1] <= res.consensus_residuals[0]

    if res.success:
        assert res.consensus_residuals[-1] < config.tolerance


def test_coordination_evaluation_no_mutation():
    """Verify evaluation logic works and does not mutate inputs."""
    nodes, edges, demands, _ = generate_world(seed=42, node_count=5, horizon_weeks=3)

    lp_res = solve_shortage_lp(nodes, edges, demands)
    ranking = rank_bottlenecks_by_shadow_price(lp_res.capacity_shadow_prices)

    targets = select_coordination_targets(ranking, top_k=2)
    features = {nid: {"shadow_price": 5.0, "shortage_delta": 10.0} for nid in targets}

    config = CoordinationConfig(max_iterations=10, capacity_step_limit=20.0)
    res = run_admm_coordination_smoke(nodes, targets, features, config)

    nodes_copy = nodes.copy()
    edges_copy = edges.copy()
    demands_copy = demands.copy()

    eval_metrics = evaluate_coordination_benefits(nodes, edges, demands, res)

    assert "baseline_shortage" in eval_metrics
    assert "coordination_shortage" in eval_metrics
    assert "shortage_reduction" in eval_metrics
    assert "total_capacity_added" in eval_metrics
    assert "reduction_per_unit_capacity" in eval_metrics

    pd.testing.assert_frame_equal(nodes, nodes_copy)
    pd.testing.assert_frame_equal(edges, edges_copy)
    pd.testing.assert_frame_equal(demands, demands_copy)


def test_coordination_package_root_exports():
    """Verify package-root exports for all coordination APIs."""
    assert hasattr(phantom_veil, "CoordinationConfig")
    assert hasattr(phantom_veil, "CoordinationResult")
    assert hasattr(phantom_veil, "select_coordination_targets")
    assert hasattr(phantom_veil, "run_admm_coordination_smoke")
    assert hasattr(phantom_veil, "evaluate_coordination_benefits")
