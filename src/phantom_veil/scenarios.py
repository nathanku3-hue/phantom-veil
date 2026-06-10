"""Scenario Perturbation and Intervention Runner for Phantom Veil (MVP-004)."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import pandas as pd

from phantom_veil.benchmark import rank_bottlenecks_by_shadow_price
from phantom_veil.io import validate_demands, validate_edges, validate_nodes
from phantom_veil.solver import solve_shortage_lp


@dataclass
class ScenarioSpec:
    """Specification of a scenario perturbation and intervention."""

    scenario_id: str
    demand_multiplier: float = 1.0
    capacity_multiplier_by_node: Dict[str, float] = field(default_factory=dict)
    delay_delta_by_edge: Dict[Tuple[str, str], int] = field(default_factory=dict)
    intervention_capacity_add_by_node: Dict[str, float] = field(default_factory=dict)
    weeks: List[int] = field(default_factory=list)


@dataclass
class ScenarioResult:
    """Typed result of running a scenario."""

    objective_value: float
    total_shortage: float
    top_shadow_price_nodes: List[str]
    weekly_shortages: Dict[int, float]


def apply_scenario(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    spec: ScenarioSpec,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Apply scenario perturbations without mutating input dataframes in place.

    Args:
        nodes: Observed nodes DataFrame.
        edges: Edges/BOM relationships DataFrame.
        demands: Weekly demands DataFrame.
        spec: ScenarioSpec containing deltas and multipliers.

    Returns:
        Tuple of (scenario_nodes, scenario_edges, scenario_demands)
    """
    # Copy to avoid in-place mutation
    nodes_df = nodes.copy()
    edges_df = edges.copy()
    demands_df = demands.copy()

    # Apply capacity multipliers and intervention additions
    for idx, row in nodes_df.iterrows():
        node_id = row["node_id"]
        cap = row["capacity"]
        if node_id in spec.capacity_multiplier_by_node:
            cap *= spec.capacity_multiplier_by_node[node_id]
        if node_id in spec.intervention_capacity_add_by_node:
            cap += spec.intervention_capacity_add_by_node[node_id]
        # Avoid non-positive capacities
        cap = max(1e-2, cap)
        nodes_df.at[idx, "capacity"] = round(float(cap), 4)

    # Apply delay deltas to edges
    for idx, row in edges_df.iterrows():
        edge_key = (row["source"], row["target"])
        if edge_key in spec.delay_delta_by_edge:
            delay = row["transit_delay_weeks"] + spec.delay_delta_by_edge[edge_key]
            edges_df.at[idx, "transit_delay_weeks"] = int(max(0, delay))

    # Apply demand multiplier to specific weeks
    target_weeks = set(spec.weeks)
    if target_weeks:
        for idx, row in demands_df.iterrows():
            if int(row["week"]) in target_weeks:
                demands_df.at[idx, "quantity"] = round(
                    float(row["quantity"] * spec.demand_multiplier), 4
                )

    # Validate output schemas
    validate_nodes(nodes_df)
    validate_edges(edges_df, nodes_df)
    validate_demands(demands_df, nodes_df)

    return nodes_df, edges_df, demands_df


def run_scenario(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    spec: ScenarioSpec,
) -> ScenarioResult:
    """Apply a scenario and run the time-expanded LP solver.

    Args:
        nodes: Observed nodes DataFrame.
        edges: Edges/BOM relationships DataFrame.
        demands: Weekly demands DataFrame.
        spec: ScenarioSpec to run.

    Returns:
        ScenarioResult object.
    """
    sc_nodes, sc_edges, sc_demands = apply_scenario(nodes, edges, demands, spec)
    res = solve_shortage_lp(sc_nodes, sc_edges, sc_demands)

    total_shortage = float(res.shortages["quantity"].sum())
    top_shadow_price_nodes = rank_bottlenecks_by_shadow_price(res.capacity_shadow_prices)

    # Compute weekly shortages summary
    weekly_shortages = {}
    weeks_list = sorted(res.shortages["week"].unique().tolist())
    for w in weeks_list:
        weekly_shortages[int(w)] = float(
            res.shortages[res.shortages["week"] == w]["quantity"].sum()
        )

    return ScenarioResult(
        objective_value=res.objective_value,
        total_shortage=total_shortage,
        top_shadow_price_nodes=top_shadow_price_nodes,
        weekly_shortages=weekly_shortages,
    )


def compare_scenarios(
    base_result: ScenarioResult,
    scenario_result: ScenarioResult,
    top_k: int = 5,
) -> dict:
    """Compare two scenario results to compute objective and shortage deltas.

    Args:
        base_result: Result from baseline scenario.
        scenario_result: Result from perturbed scenario.
        top_k: Number of top bottlenecks to compare rankings for.

    Returns:
        Dictionary of comparison metrics.
    """
    obj_delta = scenario_result.objective_value - base_result.objective_value
    shortage_delta = scenario_result.total_shortage - base_result.total_shortage
    shortage_reduction = base_result.total_shortage - scenario_result.total_shortage

    base_ranks = {node: idx + 1 for idx, node in enumerate(base_result.top_shadow_price_nodes)}
    sc_ranks = {node: idx + 1 for idx, node in enumerate(scenario_result.top_shadow_price_nodes)}

    top_k_base = base_result.top_shadow_price_nodes[:top_k]
    top_k_sc = scenario_result.top_shadow_price_nodes[:top_k]
    all_nodes = sorted(list(set(top_k_base).union(set(top_k_sc))))

    rank_changes = {}
    for node in all_nodes:
        b_rank = base_ranks.get(node, None)
        s_rank = sc_ranks.get(node, None)
        rank_changes[node] = {
            "base_rank": b_rank,
            "scenario_rank": s_rank,
            "rank_delta": (s_rank - b_rank)
            if (s_rank is not None and b_rank is not None)
            else None,
        }

    return {
        "objective_delta": round(obj_delta, 4),
        "total_shortage_delta": round(shortage_delta, 4),
        "shortage_reduction": round(shortage_reduction, 4),
        "top_k_bottleneck_rank_changes": rank_changes,
    }


def evaluate_intervention_set(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    top_k: int,
    capacity_increment: float,
) -> dict:
    """Run baseline, add capacity to top-k recommended bottlenecks, and evaluate.

    Args:
        nodes: Observed nodes DataFrame.
        edges: Edges/BOM relationships DataFrame.
        demands: Weekly demands DataFrame.
        top_k: Number of recommended bottlenecks to intervene on.
        capacity_increment: Capacity amount to add to each node.

    Returns:
        Dictionary of intervention effectiveness metrics.
    """
    base_res = solve_shortage_lp(nodes, edges, demands)
    shortage_base = float(base_res.shortages["quantity"].sum())

    top_nodes = rank_bottlenecks_by_shadow_price(base_res.capacity_shadow_prices)
    top_k_nodes = top_nodes[:top_k]

    nodes_new = nodes.copy()
    for node_id in top_k_nodes:
        nodes_new.loc[nodes_new["node_id"] == node_id, "capacity"] += capacity_increment

    new_res = solve_shortage_lp(nodes_new, edges, demands)
    shortage_new = float(new_res.shortages["quantity"].sum())

    reduction = max(0.0, shortage_base - shortage_new)
    total_added = len(top_k_nodes) * capacity_increment
    efficiency = reduction / total_added if total_added > 0.0 else 0.0

    return {
        "baseline_shortage": round(shortage_base, 4),
        "intervention_shortage": round(shortage_new, 4),
        "shortage_reduction": round(reduction, 4),
        "total_capacity_added": round(total_added, 4),
        "reduction_per_unit_capacity": round(efficiency, 4),
    }
