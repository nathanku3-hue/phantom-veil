"""Private ADMM-based Coordination Layer for capacity options consensus (MVP-008)."""

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd


@dataclass
class CoordinationConfig:
    """Configuration for ADMM coordination."""

    rho: float = 1.0
    max_iterations: int = 50
    tolerance: float = 1e-4
    top_k: int = 3
    capacity_step_limit: float = 100.0


@dataclass
class CoordinationResult:
    """Result of ADMM coordination."""

    success: bool
    iterations: int
    recommended_capacity_add_by_node: Dict[str, float]
    consensus_residuals: List[float]
    objective_trace: List[float]
    warnings: List[str]


def select_coordination_targets(
    public_ranking: List[str],
    top_k: int,
) -> List[str]:
    """Select target nodes for capacity coordination from public ranking.

    Does not consume hidden labels or true capacity.
    """
    return public_ranking[:top_k]


def _project_onto_budget(
    v_dict: Dict[str, float],
    budget: float,
    limit: float,
) -> Dict[str, float]:
    """Project vector v onto sum(z) <= budget and 0 <= z_n <= limit."""
    z_clipped = {k: max(0.0, min(limit, val)) for k, val in v_dict.items()}
    if sum(z_clipped.values()) <= budget:
        return z_clipped

    low = 0.0
    high = max(v_dict.values()) + 1.0 if v_dict else 1.0
    for _ in range(50):
        mu = (low + high) / 2.0
        total = sum(max(0.0, min(limit, val - mu)) for val in v_dict.values())
        if total > budget:
            low = mu
        else:
            high = mu

    return {k: max(0.0, min(limit, val - high)) for k, val in v_dict.items()}


def run_admm_coordination_smoke(
    nodes: pd.DataFrame,
    target_nodes: List[str],
    features: Dict[str, Dict[str, float]],
    config: CoordinationConfig,
) -> CoordinationResult:
    """Run a deterministic ADMM loop to coordinate capacity additions under budget constraint.

    Models private supplier costs locally; does not mutate input nodes DataFrame.
    """
    x = {nid: 0.0 for nid in target_nodes}
    z = {nid: 0.0 for nid in target_nodes}
    u = {nid: 0.0 for nid in target_nodes}

    c = {nid: 2.0 for nid in target_nodes}
    d = {}
    for nid in target_nodes:
        f = features.get(nid, {})
        sp = float(f.get("shadow_price", 0.0))
        sd = float(f.get("shortage_delta", 0.0))
        d[nid] = max(0.1, 10.0 * sp + 0.1 * sd)

    budget = len(target_nodes) * config.capacity_step_limit / 2.0
    consensus_residuals = []
    objective_trace = []
    success = False
    final_iter = 0

    for iteration in range(1, config.max_iterations + 1):
        z_prev = z.copy()

        for nid in target_nodes:
            numerator = config.rho * z[nid] - u[nid] + d[nid]
            denominator = config.rho + c[nid]
            val = numerator / denominator
            x[nid] = max(0.0, min(config.capacity_step_limit, val))

        v_dict = {nid: x[nid] + u[nid] / config.rho for nid in target_nodes}
        z = _project_onto_budget(v_dict, budget, config.capacity_step_limit)

        for nid in target_nodes:
            u[nid] += config.rho * (x[nid] - z[nid])

        primal_res = float(np.sqrt(sum((x[nid] - z[nid]) ** 2 for nid in target_nodes)))
        dual_res = float(
            config.rho * np.sqrt(sum((z[nid] - z_prev[nid]) ** 2 for nid in target_nodes))
        )

        consensus_residuals.append(round(primal_res, 6))
        obj_val = float(sum(0.5 * c[nid] * x[nid] ** 2 - d[nid] * x[nid] for nid in target_nodes))
        objective_trace.append(round(obj_val, 4))

        final_iter = iteration
        if primal_res < config.tolerance and dual_res < config.tolerance:
            success = True
            break
    else:
        success = primal_res < config.tolerance

    recommended = {nid: round(z[nid], 4) for nid in target_nodes}
    warnings = []
    if not success:
        warnings.append(
            f"ADMM coordination did not converge within {config.max_iterations} iterations."
        )

    return CoordinationResult(
        success=success,
        iterations=final_iter,
        recommended_capacity_add_by_node=recommended,
        consensus_residuals=consensus_residuals,
        objective_trace=objective_trace,
        warnings=warnings,
    )


def evaluate_coordination_benefits(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    coordination_result: CoordinationResult,
) -> dict:
    """Evaluate coordination recommendations using existing scenario machinery.

    Returns shortage reduction and shortage reduction per unit capacity added.
    """
    from phantom_veil.scenarios import ScenarioSpec, run_scenario

    spec_base = ScenarioSpec(scenario_id="base")
    res_base = run_scenario(nodes, edges, demands, spec_base)
    shortage_base = res_base.total_shortage

    recommendations = {
        nid: val
        for nid, val in coordination_result.recommended_capacity_add_by_node.items()
        if val > 0.0
    }

    spec_coord = ScenarioSpec(
        scenario_id="coordination_intervention",
        intervention_capacity_add_by_node=recommendations,
    )
    res_coord = run_scenario(nodes, edges, demands, spec_coord)
    shortage_coord = res_coord.total_shortage

    reduction = max(0.0, shortage_base - shortage_coord)
    total_added = sum(recommendations.values())
    efficiency = reduction / total_added if total_added > 0.0 else 0.0

    return {
        "baseline_shortage": round(shortage_base, 4),
        "coordination_shortage": round(shortage_coord, 4),
        "shortage_reduction": round(reduction, 4),
        "total_capacity_added": round(total_added, 4),
        "reduction_per_unit_capacity": round(efficiency, 4),
    }
