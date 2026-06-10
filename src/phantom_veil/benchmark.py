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
        Dictionary containing precision, recall, and f1.
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
        Dictionary containing average precision, recall, and f1 metrics.
    """
    from phantom_veil.solver import solve_shortage_lp
    from phantom_veil.worldgen import generate_world

    total_precision = 0.0
    total_recall = 0.0
    total_f1 = 0.0
    detailed_results = []

    for seed in seeds:
        nodes, edges, demands, bottlenecks = generate_world(
            seed=seed, node_count=node_count, horizon_weeks=horizon_weeks
        )

        if use_true_capacities:
            nodes = nodes.copy()
            for idx, row in nodes.iterrows():
                nid = row["node_id"]
                true_cap = bottlenecks[bottlenecks["node_id"] == nid].iloc[0]["true_capacity"]
                nodes.loc[idx, "capacity"] = true_cap

        res = solve_shortage_lp(nodes, edges, demands)

        gt = bottlenecks[bottlenecks["is_hidden_bottleneck"]]["node_id"].tolist()
        predictions = rank_bottlenecks_by_shadow_price(res.capacity_shadow_prices)

        metrics = score_predictions(predictions, gt, top_k=top_k)

        total_precision += metrics["precision"]
        total_recall += metrics["recall"]
        total_f1 += metrics["f1"]

        detailed_results.append(
            {
                "seed": seed,
                "ground_truth": gt,
                "predictions": predictions[:top_k],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "f1": metrics["f1"],
            }
        )

    n_seeds = len(seeds)
    return {
        "avg_precision": (round(total_precision / n_seeds, 4) if n_seeds > 0 else 0.0),
        "avg_recall": round(total_recall / n_seeds, 4) if n_seeds > 0 else 0.0,
        "avg_f1": round(total_f1 / n_seeds, 4) if n_seeds > 0 else 0.0,
        "detailed_results": detailed_results,
    }
