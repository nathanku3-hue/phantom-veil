"""Tests for the Phantom Bottleneck Benchmark Harness (MVP-003)."""

from phantom_veil.benchmark import run_benchmark_suite, score_predictions


def test_score_predictions_calculations():
    """Verify precision, recall, and F1 score math logic."""
    predicted = ["N_001", "N_002", "N_003"]
    ground_truth = ["N_002", "N_004"]

    # 1. Evaluate top 2 predictions: ["N_001", "N_002"]
    # Intersection = {"N_002"} (1 TP)
    # Precision = 1 / 2 = 0.5
    # Recall = 1 / 2 = 0.5
    # F1 = 2 * 0.5 * 0.5 / (0.5 + 0.5) = 0.5
    metrics = score_predictions(predicted, ground_truth, top_k=2)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5

    # 2. Evaluate top 1 prediction: ["N_001"]
    # Intersection = {} (0 TP)
    metrics_top_1 = score_predictions(predicted, ground_truth, top_k=1)
    assert metrics_top_1["precision"] == 0.0
    assert metrics_top_1["recall"] == 0.0
    assert metrics_top_1["f1"] == 0.0


def test_benchmark_suite_recall_threshold():
    """Verify that the benchmark suite runs and achieves high recall on default worlds."""
    # Run over 5 deterministic seeds
    seeds = [11, 22, 33, 44, 55]

    # Node count 30 so the solving is fast
    res = run_benchmark_suite(
        seeds=seeds,
        node_count=30,
        horizon_weeks=26,
        top_k=3,
        use_true_capacities=True,
    )

    # Check metrics existence
    assert "avg_precision" in res
    assert "avg_recall" in res
    assert "avg_f1" in res
    assert "precision@k" in res
    assert "recall@k" in res
    assert "top_k_overlap" in res
    assert "shortage_reduction" in res
    assert len(res["detailed_results"]) == len(seeds)

    # Check detailed results schema
    for item in res["detailed_results"]:
        assert "top_k_overlap" in item
        assert "overlap_count" in item
        assert "shortage_reduction" in item

    # Assert recall threshold meets the expected active bottleneck identification target.
    # Since only 1 of the 2 bottlenecks is active (the other is starved), the maximum recall is 0.5.
    # Therefore, 0.45 average recall indicates correct identification of the active bottlenecks.
    assert res["avg_recall"] >= 0.45
    assert res["recall@k"] >= 0.45
    assert res["shortage_reduction"] >= 0.0
