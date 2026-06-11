"""Continuous Queue Dynamics ODE Adapter using SciPy BDF/implicit solver (MVP-006)."""

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp

from phantom_veil.scenarios import ScenarioResult


@dataclass
class QueueDynamicsConfig:
    """Configuration for continuous queue dynamics simulation."""

    method: str = "BDF"
    rtol: float = 1e-4
    atol: float = 1e-6
    horizon_days: int = 30
    top_k: int = 2
    utilization_warning_threshold: float = 0.90
    max_lead_time_multiplier: float = 5.0


@dataclass
class QueueDynamicsResult:
    """Result of continuous queue dynamics simulation."""

    success: bool
    method: str
    simulated_nodes: List[str]
    time_grid: List[float]
    queue_by_node: Dict[str, List[float]]
    utilization_by_node: Dict[str, List[float]]
    lead_time_multiplier_by_node: Dict[str, List[float]]
    warnings: List[str]


def select_dynamic_nodes(
    baseline_scenario_result: ScenarioResult,
    top_k: int,
) -> List[str]:
    """Select the top-k nodes by peak LP shadow price.

    Does not use hidden bottleneck labels.
    """
    return baseline_scenario_result.top_shadow_price_nodes[:top_k]


def _propagate_demand_pressure(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
) -> Dict[str, np.ndarray]:
    """Propagate unconstrained demand pressure upstream through tiers."""
    W = int(demands["week"].max())
    demand_pressure = {nid: np.zeros(W + 1) for nid in nodes["node_id"]}

    for _, row in demands.iterrows():
        sku = row["sku_id"]
        w = int(row["week"])
        if sku in demand_pressure and w <= W:
            demand_pressure[sku][w] = row["quantity"]

    for tier in [1, 2, 3]:
        for _, edge in edges.iterrows():
            parent = edge["source"]
            child = edge["target"]
            bom = edge["bom_ratio"]
            delay = int(edge["transit_delay_weeks"])

            child_tier = nodes[nodes["node_id"] == child].iloc[0]["tier"]
            if child_tier == tier:
                for w in range(1, W + 1):
                    if w + delay <= W:
                        demand_pressure[parent][w] += demand_pressure[child][w + delay] * bom

    return demand_pressure


def simulate_queue_dynamics(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    baseline_scenario_result: ScenarioResult,
    config: QueueDynamicsConfig,
) -> QueueDynamicsResult:
    """Integrate queue state Q(t) and compute utilization/lead-time multipliers.

    Uses scipy.integrate.solve_ivp.
    """
    valid_methods = {"RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA"}
    if config.method not in valid_methods:
        raise ValueError(
            f"Unsupported solver method '{config.method}'. "
            f"Supported methods are: {sorted(list(valid_methods))}"
        )

    selected_nodes = select_dynamic_nodes(baseline_scenario_result, config.top_k)
    if not selected_nodes:
        t_eval = np.linspace(0.0, float(config.horizon_days), int(config.horizon_days) + 1)
        return QueueDynamicsResult(
            success=True,
            method=config.method,
            simulated_nodes=[],
            time_grid=t_eval.tolist(),
            queue_by_node={},
            utilization_by_node={},
            lead_time_multiplier_by_node={},
            warnings=["Warning: No bottleneck nodes were selected for dynamics simulation."],
        )

    W = int(demands["week"].max())
    demand_pressure = _propagate_demand_pressure(nodes, edges, demands)

    def get_arrival_rate(node_id: str, t: float) -> float:
        w_indices = np.arange(1, W + 1)
        rates = demand_pressure[node_id][1:] / 7.0
        return float(np.interp(t / 7.0, w_indices - 1, rates, left=rates[0], right=rates[-1]))

    t_span = (0.0, float(config.horizon_days))
    t_eval = np.linspace(0.0, float(config.horizon_days), int(config.horizon_days) + 1)
    y0 = np.zeros(len(selected_nodes))

    def ode_system(t, y):
        dydt = []
        for i, node_id in enumerate(selected_nodes):
            q = y[i]
            arr = get_arrival_rate(node_id, t)
            cap_day = float(nodes[nodes["node_id"] == node_id].iloc[0]["capacity"]) / 7.0
            service = cap_day * np.tanh(max(0.0, q))
            dydt.append(arr - service)
        return dydt

    sol = solve_ivp(
        fun=ode_system,
        t_span=t_span,
        y0=y0,
        method=config.method,
        t_eval=t_eval,
        rtol=config.rtol,
        atol=config.atol,
    )

    if not sol.success or sol.status < 0:
        raise RuntimeError(f"ODE Solver failed: {sol.message}")

    return _build_dynamics_result(sol, nodes, selected_nodes, get_arrival_rate, config)


def _build_dynamics_result(
    sol,
    nodes: pd.DataFrame,
    selected_nodes: List[str],
    get_arrival_rate,
    config: QueueDynamicsConfig,
) -> QueueDynamicsResult:
    """Helper to parse ODE solution and build QueueDynamicsResult."""
    time_grid = sol.t.tolist()
    queue_by_node = {nid: [] for nid in selected_nodes}
    utilization_by_node = {nid: [] for nid in selected_nodes}
    lead_time_multiplier_by_node = {nid: [] for nid in selected_nodes}
    warnings = []

    for t_idx, t in enumerate(time_grid):
        for i, nid in enumerate(selected_nodes):
            q = max(0.0, float(sol.y[i, t_idx]))
            arr = get_arrival_rate(nid, t)
            cap_day = float(nodes[nodes["node_id"] == nid].iloc[0]["capacity"]) / 7.0
            util = arr / cap_day if cap_day > 0 else 0.0
            lt_mult = (
                min(config.max_lead_time_multiplier, 1.0 + q / cap_day) if cap_day > 0 else 1.0
            )

            queue_by_node[nid].append(round(q, 4))
            utilization_by_node[nid].append(round(util, 4))
            lead_time_multiplier_by_node[nid].append(round(lt_mult, 4))

    for nid in selected_nodes:
        max_util = max(utilization_by_node[nid])
        if max_util >= config.utilization_warning_threshold:
            warnings.append(
                f"Warning: Node {nid} exceeded utilization threshold "
                f"(max: {max_util:.2f} >= {config.utilization_warning_threshold:.2f})"
            )

    return QueueDynamicsResult(
        success=bool(sol.success),
        method=config.method,
        simulated_nodes=selected_nodes,
        time_grid=time_grid,
        queue_by_node=queue_by_node,
        utilization_by_node=utilization_by_node,
        lead_time_multiplier_by_node=lead_time_multiplier_by_node,
        warnings=warnings,
    )


def summarize_dynamic_risk(result: QueueDynamicsResult) -> dict:
    """Summarize dynamic risks from simulated queue results."""
    summary = {
        "max_utilization_by_node": {},
        "max_queue_by_node": {},
        "max_lead_time_multiplier_by_node": {},
        "warnings": result.warnings,
    }
    for nid in result.simulated_nodes:
        summary["max_utilization_by_node"][nid] = max(result.utilization_by_node[nid])
        summary["max_queue_by_node"][nid] = max(result.queue_by_node[nid])
        summary["max_lead_time_multiplier_by_node"][nid] = max(
            result.lead_time_multiplier_by_node[nid]
        )

    return summary
