"""Offline bottleneck classification and benchmark evaluator for Phantom Veil."""

from typing import List

import pandas as pd


def score_predictions(
    predicted_ranking: List[str],
    ground_truth_bottlenecks: List[str],
    top_k: int = 2,
) -> dict:
    """Compute precision, recall, and F1-score for top-k predicted nodes.

    Args:
        predicted_ranking: List of node IDs sorted by prediction confidence.
        ground_truth_bottlenecks: List of true hidden bottleneck node IDs.
        top_k: Look at the top-k predictions.

    Returns:
        Dictionary containing precision, recall, f1, overlap_nodes, and overlap_count.
    """
    predicted_set = set(predicted_ranking[:top_k])
    ground_truth_set = set(ground_truth_bottlenecks)

    true_positives = len(predicted_set.intersection(ground_truth_set))

    precision = true_positives / len(predicted_set) if len(predicted_set) > 0 else 0.0
    recall = true_positives / len(ground_truth_set) if len(ground_truth_set) > 0 else 0.0

    f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) > 0.0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "overlap_nodes": sorted(list(predicted_set.intersection(ground_truth_set))),
        "overlap_count": true_positives,
    }


def rank_bottlenecks_by_shadow_price(shadow_prices: pd.DataFrame) -> List[str]:
    """Rank nodes by their peak capacity shadow price across all weeks.

    Args:
        shadow_prices: DataFrame containing capacity_shadow_value columns.

    Returns:
        List of node IDs sorted descending by peak shadow value.
    """
    summary = shadow_prices.groupby("node_id")["capacity_shadow_value"].max().reset_index()
    summary = summary.sort_values(by="capacity_shadow_value", ascending=False)
    return summary["node_id"].tolist()


def _compute_shortage_reduction(
    nodes_baseline: pd.DataFrame,
    nodes_nominal: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    top_k_preds: List[str],
    shortage_base: float,
) -> float:
    """Helper to calculate shortage reduction after restoring top-k nodes to nominal."""
    from phantom_veil.solver import solve_shortage_lp

    nodes_fixed = nodes_baseline.copy()
    for node_id in top_k_preds:
        nom_cap = nodes_nominal[nodes_nominal["node_id"] == node_id].iloc[0]["capacity"]
        nodes_fixed.loc[nodes_fixed["node_id"] == node_id, "capacity"] = nom_cap

    res_fixed = solve_shortage_lp(nodes_fixed, edges, demands)
    shortage_fixed = float(res_fixed.shortages["quantity"].sum())
    return round(max(0.0, shortage_base - shortage_fixed), 4)


def run_benchmark_suite(
    seeds: List[int],
    node_count: int = 50,
    horizon_weeks: int = 52,
    top_k: int = 2,
    use_true_capacities: bool = True,
) -> dict:
    """Run the bottleneck evaluation benchmark over a set of seeds.

    Args:
        seeds: List of seeds to evaluate on.
        node_count: Total number of nodes per generated world.
        horizon_weeks: Planning horizon in weeks.
        top_k: Select top-k predictions to evaluate.
        use_true_capacities: If True, solves LP using ground-truth capacities.

    Returns:
        Dictionary containing average precision, recall, and f1 metrics,
        plus shortage reduction and detailed per-seed results.
    """
    from phantom_veil.solver import solve_shortage_lp
    from phantom_veil.worldgen import generate_world

    sums = {"precision": 0.0, "recall": 0.0, "f1": 0.0, "overlap": 0.0, "reduction": 0.0}
    detailed_results = []

    for seed in seeds:
        nodes, edges, demands, bottlenecks = generate_world(
            seed=seed, node_count=node_count, horizon_weeks=horizon_weeks
        )

        nodes_baseline = nodes.copy()
        if use_true_capacities:
            for idx, row in nodes_baseline.iterrows():
                nid = row["node_id"]
                true_cap = bottlenecks[bottlenecks["node_id"] == nid].iloc[0]["true_capacity"]
                nodes_baseline.loc[idx, "capacity"] = true_cap

        res = solve_shortage_lp(nodes_baseline, edges, demands)
        shortage_base = float(res.shortages["quantity"].sum())

        gt = bottlenecks[bottlenecks["is_hidden_bottleneck"]]["node_id"].tolist()
        predictions = rank_bottlenecks_by_shadow_price(res.capacity_shadow_prices)

        metrics = score_predictions(predictions, gt, top_k=top_k)
        top_k_preds = predictions[:top_k]

        reduction = 0.0
        if use_true_capacities and len(top_k_preds) > 0:
            reduction = _compute_shortage_reduction(
                nodes_baseline, nodes, edges, demands, top_k_preds, shortage_base
            )

        sums["precision"] += metrics["precision"]
        sums["recall"] += metrics["recall"]
        sums["f1"] += metrics["f1"]
        sums["overlap"] += metrics["overlap_count"]
        sums["reduction"] += reduction

        detailed_results.append(
            {
                "seed": seed,
                "ground_truth": gt,
                "predictions": top_k_preds,
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "f1": metrics["f1"],
                "top_k_overlap": metrics["overlap_nodes"],
                "overlap_count": metrics["overlap_count"],
                "shortage_reduction": reduction,
            }
        )

    n = len(seeds)
    div = n if n > 0 else 1
    return {
        "avg_precision": round(sums["precision"] / div, 4) if n > 0 else 0.0,
        "avg_recall": round(sums["recall"] / div, 4) if n > 0 else 0.0,
        "avg_f1": round(sums["f1"] / div, 4) if n > 0 else 0.0,
        "precision@k": round(sums["precision"] / div, 4) if n > 0 else 0.0,
        "recall@k": round(sums["recall"] / div, 4) if n > 0 else 0.0,
        "top_k_overlap": round(sums["overlap"] / div, 4) if n > 0 else 0.0,
        "shortage_reduction": round(sums["reduction"] / div, 4) if n > 0 else 0.0,
        "detailed_results": detailed_results,
    }
