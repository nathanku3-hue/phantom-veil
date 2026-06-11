"""Tests for the Inverse Bottleneck Signal Extractor (MVP-007)."""

import pandas as pd

from phantom_veil.inverse import (
    InverseConfig,
    build_inverse_features,
    evaluate_inverse_against_ground_truth,
    rank_inverse_bottlenecks,
)


def test_inverse_extractor_no_leakage_and_graceful_missing():
    """Verify that features build and rank without hidden labels and handle missing risk."""
    nodes = pd.DataFrame(
        [
            {"node_id": "N1", "capacity": 10},
            {"node_id": "N2", "capacity": 20},
            {"node_id": "N3", "capacity": 30},
        ]
    )

    # Do not include is_hidden_bottleneck or true_capacity here to prove no leakage
    capacity_shadow_prices = pd.DataFrame(
        [
            {"node_id": "N1", "week": 1, "capacity_shadow_value": 5.0, "raw_marginal": -5.0},
            {"node_id": "N2", "week": 1, "capacity_shadow_value": 2.0, "raw_marginal": -2.0},
        ]
    )

    scenario_shortage_deltas = {"N1": 15.0, "N2": 5.0, "N3": 0.0}
    intervention_efficiencies = {"N1": 0.8, "N2": 0.4, "N3": 0.0}

    # Build features without dynamic risk input to test graceful handling
    features = build_inverse_features(
        nodes=nodes,
        capacity_shadow_prices=capacity_shadow_prices,
        scenario_shortage_deltas=scenario_shortage_deltas,
        intervention_efficiencies=intervention_efficiencies,
        dynamic_utilizations=None,
        dynamic_lead_time_multipliers=None,
    )

    assert "N1" in features
    assert "N2" in features
    assert "N3" in features

    assert features["N1"]["shadow_price"] == 5.0
    assert features["N3"]["shadow_price"] == 0.0
    assert features["N1"]["dynamic_utilization"] == 0.0
    assert features["N1"]["dynamic_lead_time_multiplier"] == 1.0

    # Rank bottlenecks
    config = InverseConfig(top_k=2)
    res = rank_inverse_bottlenecks(features, config)

    assert len(res.ranked_nodes) == 2
    assert res.ranked_nodes == ["N1", "N2"]

    # Verify no leakage: ensure result object does not hold private labels or capacities
    assert "is_hidden_bottleneck" not in res.node_scores
    assert "true_capacity" not in res.node_scores


def test_inverse_extractor_deterministic_and_tie_breaking():
    """Verify that ranking is deterministic and resolves ties stably using node_id."""
    nodes = pd.DataFrame(
        [
            {"node_id": "B_node", "capacity": 10},
            {"node_id": "A_node", "capacity": 10},
            {"node_id": "C_node", "capacity": 10},
        ]
    )

    # All nodes have identical features to force tie-breaking
    capacity_shadow_prices = pd.DataFrame(
        [
            {"node_id": "B_node", "week": 1, "capacity_shadow_value": 1.0, "raw_marginal": -1.0},
            {"node_id": "A_node", "week": 1, "capacity_shadow_value": 1.0, "raw_marginal": -1.0},
            {"node_id": "C_node", "week": 1, "capacity_shadow_value": 1.0, "raw_marginal": -1.0},
        ]
    )

    features = build_inverse_features(
        nodes=nodes,
        capacity_shadow_prices=capacity_shadow_prices,
        scenario_shortage_deltas={},
        intervention_efficiencies={},
    )

    config = InverseConfig(top_k=3)
    res1 = rank_inverse_bottlenecks(features, config)
    res2 = rank_inverse_bottlenecks(features, config)

    # Verify determinism
    assert res1.ranked_nodes == res2.ranked_nodes
    assert res1.node_scores == res2.node_scores

    # Verify stable tie-breaking: alphabetical ascending order (A_node, B_node, C_node)
    assert res1.ranked_nodes == ["A_node", "B_node", "C_node"]


def test_inverse_extractor_evaluation():
    """Verify evaluation logic using ground-truth labels."""
    features = {
        "N1": {"shadow_price": 10.0, "shortage_delta": 5.0},
        "N2": {"shadow_price": 5.0, "shortage_delta": 2.0},
        "N3": {"shadow_price": 0.0, "shortage_delta": 0.0},
    }

    config = InverseConfig(top_k=2)
    res = rank_inverse_bottlenecks(features, config)

    # N1 and N2 are predicted top 2.
    # Ground truth hidden bottlenecks are N1 and N3.
    ground_truth = ["N1", "N3"]

    eval_res = evaluate_inverse_against_ground_truth(res, ground_truth, top_k=2)

    # Precision@2 = 1 / 2 = 0.5
    # Recall@2 = 1 / 2 = 0.5
    # Overlap = ["N1"]
    assert eval_res["precision"] == 0.5
    assert eval_res["recall"] == 0.5
    assert eval_res["precision@k"] == 0.5
    assert eval_res["recall@k"] == 0.5
    assert eval_res["overlap"] == ["N1"]
