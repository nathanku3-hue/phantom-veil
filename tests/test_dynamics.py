"""Tests for the Continuous Queue Dynamics ODE Adapter (MVP-006)."""

import pytest

from phantom_veil.dynamics import (
    QueueDynamicsConfig,
    select_dynamic_nodes,
    simulate_queue_dynamics,
    summarize_dynamic_risk,
)
from phantom_veil.scenarios import ScenarioSpec, run_scenario
from phantom_veil.worldgen import generate_world


def _setup_dynamics_data():
    nodes, edges, demands, bottlenecks = generate_world(seed=42, node_count=10, horizon_weeks=5)
    spec_base = ScenarioSpec(scenario_id="base")
    res_base = run_scenario(nodes, edges, demands, spec_base)
    return nodes, edges, demands, bottlenecks, res_base


def test_select_dynamic_nodes_lp_only():
    """Verify that selected dynamic nodes come only from LP shadow-price rankings."""
    nodes, edges, demands, bottlenecks, res_base = _setup_dynamics_data()

    top_k = 2
    selected = select_dynamic_nodes(res_base, top_k)

    # Assert they match baseline shadow price order
    assert selected == res_base.top_shadow_price_nodes[:top_k]

    # Check no hidden labels or true capacities are used
    assert not hasattr(res_base, "is_hidden_bottleneck")
    assert not hasattr(res_base, "true_capacity")


def test_deterministic_queue_simulation():
    """Verify that queue dynamics simulation is deterministic."""
    nodes, edges, demands, _, res_base = _setup_dynamics_data()

    config = QueueDynamicsConfig(
        method="BDF",
        horizon_days=15,
        top_k=2,
        utilization_warning_threshold=0.80,
    )

    res1 = simulate_queue_dynamics(nodes, edges, demands, res_base, config)
    res2 = simulate_queue_dynamics(nodes, edges, demands, res_base, config)

    assert res1.success is True
    assert res1.success == res2.success
    assert res1.method == res2.method
    assert res1.simulated_nodes == res2.simulated_nodes
    assert res1.time_grid == res2.time_grid
    assert res1.queue_by_node == res2.queue_by_node
    assert res1.utilization_by_node == res2.utilization_by_node
    assert res1.lead_time_multiplier_by_node == (res2.lead_time_multiplier_by_node)
    assert res1.warnings == res2.warnings


def test_dynamics_output_schema_and_risk_summary():
    """Verify the result schema, fields, and summary structure."""
    nodes, edges, demands, _, res_base = _setup_dynamics_data()

    config = QueueDynamicsConfig(
        method="BDF",
        horizon_days=20,
        top_k=2,
    )

    res = simulate_queue_dynamics(nodes, edges, demands, res_base, config)

    assert isinstance(res.success, bool)
    assert res.method == "BDF"
    assert len(res.simulated_nodes) == 2
    assert len(res.time_grid) == 21  # 0 to 20 inclusive
    assert set(res.queue_by_node.keys()) == set(res.simulated_nodes)
    assert set(res.utilization_by_node.keys()) == set(res.simulated_nodes)
    assert set(res.lead_time_multiplier_by_node.keys()) == set(res.simulated_nodes)

    summary = summarize_dynamic_risk(res)
    assert "max_utilization_by_node" in summary
    assert "max_queue_by_node" in summary
    assert "max_lead_time_multiplier_by_node" in summary
    assert "warnings" in summary

    for nid in res.simulated_nodes:
        assert summary["max_utilization_by_node"][nid] >= 0.0
        assert summary["max_queue_by_node"][nid] >= 0.0
        assert summary["max_lead_time_multiplier_by_node"][nid] >= 1.0


def test_high_utilization_creates_warning():
    """Verify that exceeding the utilization warning threshold creates warnings."""
    nodes, edges, demands, _, res_base = _setup_dynamics_data()

    # Set threshold to a very low value to force warning
    config = QueueDynamicsConfig(
        method="BDF",
        horizon_days=10,
        top_k=1,
        utilization_warning_threshold=0.01,
    )

    res = simulate_queue_dynamics(nodes, edges, demands, res_base, config)
    assert len(res.warnings) > 0
    assert any("exceeded utilization threshold" in w for w in res.warnings)


def test_solve_ivp_failure_handling(monkeypatch):
    """Verify that solve_ivp failures raise useful errors."""
    nodes, edges, demands, _, res_base = _setup_dynamics_data()

    config = QueueDynamicsConfig(method="BDF", horizon_days=10)

    class MockSol:
        success = False
        status = -2
        message = "Stiff step size underflow in BDF solver."

    monkeypatch.setattr("phantom_veil.dynamics.solve_ivp", lambda *args, **kwargs: MockSol())

    with pytest.raises(RuntimeError, match="ODE Solver failed: Stiff step size underflow."):
        simulate_queue_dynamics(nodes, edges, demands, res_base, config)


def test_dynamics_unsupported_method():
    """Verify that unsupported solver methods raise ValueError."""
    nodes, edges, demands, _, res_base = _setup_dynamics_data()
    config = QueueDynamicsConfig(method="NONEXISTENT")
    with pytest.raises(ValueError, match="Unsupported solver method"):
        simulate_queue_dynamics(nodes, edges, demands, res_base, config)


def test_dynamics_empty_selected_nodes_or_large_top_k():
    """Verify dynamics when top_k is 0 or exceeds available nodes."""
    nodes, edges, demands, _, res_base = _setup_dynamics_data()

    # Case 1: top_k is 0 (no nodes selected)
    config_zero = QueueDynamicsConfig(top_k=0)
    res_zero = simulate_queue_dynamics(nodes, edges, demands, res_base, config_zero)
    assert res_zero.success is True
    assert len(res_zero.simulated_nodes) == 0
    assert len(res_zero.warnings) > 0
    assert "Warning: No bottleneck nodes were selected" in res_zero.warnings[0]

    # Case 2: top_k is extremely large
    config_large = QueueDynamicsConfig(top_k=1000)
    res_large = simulate_queue_dynamics(nodes, edges, demands, res_base, config_large)
    assert res_large.success is True
    # Should slice gracefully to maximum available shadow price nodes
    assert len(res_large.simulated_nodes) == len(res_base.top_shadow_price_nodes)
