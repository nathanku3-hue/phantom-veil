"""Inverse Bottleneck Signal Extractor for Phantom Veil (MVP-007)."""

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd


@dataclass
class InverseConfig:
    """Configuration for inverse bottleneck signal extractor."""

    top_k: int = 3
    shadow_price_weight: float = 1.0
    shortage_weight: float = 1.0
    dynamic_risk_weight: float = 1.0
    robust_scale: float = 1.0


@dataclass
class InverseResult:
    """Result from inverse bottleneck signal extractor."""

    ranked_nodes: List[str]
    node_scores: Dict[str, float]
    feature_table: Dict[str, Dict[str, float]]
    warnings: List[str]


def build_inverse_features(
    nodes: pd.DataFrame,
    capacity_shadow_prices: pd.DataFrame,
    scenario_shortage_deltas: Dict[str, float],
    intervention_efficiencies: Dict[str, float],
    dynamic_utilizations: Dict[str, float] = None,
    dynamic_lead_time_multipliers: Dict[str, float] = None,
) -> Dict[str, Dict[str, float]]:
    """Build a feature table of public signals for inverse bottleneck inference.

    Args:
        nodes: DataFrame containing observed node_ids.
        capacity_shadow_prices: DataFrame containing LP capacity shadow prices.
        scenario_shortage_deltas: Dict mapping node_id to shortage change under scenario.
        intervention_efficiencies: Dict mapping node_id to shortage reduction per unit added.
        dynamic_utilizations: Dict mapping node_id to peak/average dynamic utilization.
        dynamic_lead_time_multipliers: Dict mapping node_id to dynamic lead time multiplier.

    Returns:
        Dict mapping node_id to Dict of public features.
    """
    feature_table = {}

    peak_shadow_prices = {}
    if not capacity_shadow_prices.empty and "node_id" in capacity_shadow_prices.columns:
        grouped = capacity_shadow_prices.groupby("node_id")["capacity_shadow_value"].max()
        peak_shadow_prices = grouped.to_dict()

    dyn_util = dynamic_utilizations or {}
    dyn_lt = dynamic_lead_time_multipliers or {}

    for node_id in nodes["node_id"]:
        feature_table[node_id] = {
            "shadow_price": float(peak_shadow_prices.get(node_id, 0.0)),
            "shortage_delta": float(scenario_shortage_deltas.get(node_id, 0.0)),
            "intervention_efficiency": float(intervention_efficiencies.get(node_id, 0.0)),
            "dynamic_utilization": float(dyn_util.get(node_id, 0.0)),
            "dynamic_lead_time_multiplier": float(dyn_lt.get(node_id, 1.0)),
        }

    return feature_table


def rank_inverse_bottlenecks(
    feature_table: Dict[str, Dict[str, float]],
    config: InverseConfig,
) -> InverseResult:
    """Deterministically score and rank nodes using the feature table and weights.

    Uses no hidden labels or ground-truth capacities. Tie-breaks stably by node_id.
    """
    node_scores = {}
    warnings = []

    for node_id, features in feature_table.items():
        shadow_p = features.get("shadow_price", 0.0)
        shortage_d = features.get("shortage_delta", 0.0)
        dyn_util = features.get("dynamic_utilization", 0.0)
        dyn_lt = features.get("dynamic_lead_time_multiplier", 1.0)

        # Dynamic risk combined from utilization and lead-time multiplier (defaults to 1.0)
        dynamic_risk = dyn_util + max(0.0, dyn_lt - 1.0)

        raw_score = (
            config.shadow_price_weight * shadow_p
            + config.shortage_weight * shortage_d
            + config.dynamic_risk_weight * dynamic_risk
        )
        score = raw_score * config.robust_scale
        node_scores[node_id] = round(float(score), 4)

    # Sort descending by score, tie-break by node_id alphabetically ascending
    sorted_nodes = sorted(node_scores.keys(), key=lambda nid: (-node_scores[nid], nid))

    ranked_nodes = sorted_nodes[: config.top_k]

    return InverseResult(
        ranked_nodes=ranked_nodes,
        node_scores=node_scores,
        feature_table=feature_table,
        warnings=warnings,
    )


def evaluate_inverse_against_ground_truth(
    inverse_result: InverseResult,
    ground_truth_bottlenecks: List[str],
    top_k: int,
) -> dict:
    """Evaluate predicted ranked_nodes against ground-truth hidden bottlenecks.

    Can use hidden bottleneck labels.
    """
    predicted_set = set(inverse_result.ranked_nodes[:top_k])
    ground_truth_set = set(ground_truth_bottlenecks)

    true_positives = len(predicted_set.intersection(ground_truth_set))

    precision = true_positives / len(predicted_set) if len(predicted_set) > 0 else 0.0
    recall = true_positives / len(ground_truth_set) if len(ground_truth_set) > 0 else 0.0

    overlap = sorted(list(predicted_set.intersection(ground_truth_set)))

    return {
        "precision@k": round(precision, 4),
        "recall@k": round(recall, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "overlap": overlap,
        "overlap_count": true_positives,
    }
