"""Tests for the Decision Report Generator (MVP-005)."""

import json

from phantom_veil.benchmark import run_benchmark_suite
from phantom_veil.reporting import (
    ReportConfig,
    build_decision_report,
    export_report_json,
    export_report_markdown,
)
from phantom_veil.scenarios import ScenarioSpec, evaluate_intervention_set, run_scenario
from phantom_veil.worldgen import generate_world


def _setup_report_data():
    """Helper to generate standard data for reporting tests."""
    nodes, edges, demands, bottlenecks = generate_world(seed=42, node_count=10, horizon_weeks=5)

    config = ReportConfig(
        report_id="R_TEST_001",
        seed=42,
        top_k=2,
        scenario_ids=["perturbed_demand_shock"],
        include_benchmark_summary=True,
        include_intervention_summary=True,
    )

    # Solve baseline
    spec_base = ScenarioSpec(scenario_id="base")
    res_base = run_scenario(nodes, edges, demands, spec_base)

    # Solve perturbed
    spec_perturbed = ScenarioSpec(
        scenario_id="perturbed_demand_shock",
        demand_multiplier=2.0,
        weeks=[2, 3],
    )
    res_perturbed = run_scenario(nodes, edges, demands, spec_perturbed)
    perturbed_results = {"perturbed_demand_shock": res_perturbed}

    # Intervention evaluation
    interv_metrics = evaluate_intervention_set(
        nodes, edges, demands, top_k=2, capacity_increment=100.0
    )

    # Benchmark results
    bench_res = run_benchmark_suite(
        seeds=[42],
        node_count=10,
        horizon_weeks=5,
        top_k=2,
        use_true_capacities=True,
    )

    return (
        nodes,
        edges,
        demands,
        bottlenecks,
        config,
        res_base,
        perturbed_results,
        interv_metrics,
        bench_res,
    )


def test_deterministic_report_generation():
    """Verify that report generation is fully deterministic."""
    (
        nodes,
        edges,
        demands,
        _,
        config,
        res_base,
        perturbed,
        interv,
        bench,
    ) = _setup_report_data()

    rep1 = build_decision_report(
        nodes,
        edges,
        demands,
        config,
        benchmark_results=bench,
        baseline_result=res_base,
        perturbed_results=perturbed,
        intervention_metrics=interv,
    )

    rep2 = build_decision_report(
        nodes,
        edges,
        demands,
        config,
        benchmark_results=bench,
        baseline_result=res_base,
        perturbed_results=perturbed,
        intervention_metrics=interv,
    )

    # Verify object equality
    assert rep1.executive_summary == rep2.executive_summary
    assert rep1.top_bottlenecks == rep2.top_bottlenecks
    assert rep1.shadow_price_summary == rep2.shadow_price_summary
    assert rep1.scenario_comparison == rep2.scenario_comparison
    assert rep1.intervention_recommendations == rep2.intervention_recommendations
    assert rep1.benchmark_quality == rep2.benchmark_quality
    assert rep1.model_limitations == rep2.model_limitations

    # Verify markdown export is identical
    md1 = export_report_markdown(rep1)
    md2 = export_report_markdown(rep2)
    assert md1 == md2

    # Verify JSON export is identical
    js1 = export_report_json(rep1)
    js2 = export_report_json(rep2)
    assert js1 == js2


def test_required_report_sections_exist():
    """Verify that all required sections are present and populated."""
    (
        nodes,
        edges,
        demands,
        _,
        config,
        res_base,
        perturbed,
        interv,
        bench,
    ) = _setup_report_data()

    report = build_decision_report(
        nodes,
        edges,
        demands,
        config,
        benchmark_results=bench,
        baseline_result=res_base,
        perturbed_results=perturbed,
        intervention_metrics=interv,
    )

    assert report.executive_summary != ""
    assert isinstance(report.top_bottlenecks, list)
    assert len(report.top_bottlenecks) == config.top_k
    assert report.shadow_price_summary != ""
    assert report.scenario_comparison != ""
    assert report.intervention_recommendations != ""
    assert report.benchmark_quality != ""
    assert report.model_limitations != ""


def test_markdown_and_json_exports():
    """Verify markdown contents and JSON serializability."""
    (
        nodes,
        edges,
        demands,
        _,
        config,
        res_base,
        perturbed,
        interv,
        bench,
    ) = _setup_report_data()

    report = build_decision_report(
        nodes,
        edges,
        demands,
        config,
        benchmark_results=bench,
        baseline_result=res_base,
        perturbed_results=perturbed,
        intervention_metrics=interv,
    )

    # Markdown checks
    md_content = export_report_markdown(report)
    assert "# Decision Report: R_TEST_001" in md_content
    assert "## Executive Summary" in md_content
    assert "## Top Bottlenecks" in md_content
    assert "Node ID" in md_content
    assert "Process Class" in md_content
    assert "Geographic Region" in md_content
    assert "Scenario 'perturbed_demand_shock':" in md_content
    assert "Intervention set evaluation" in md_content
    assert "intervention efficiency" in md_content or "reduction per unit capacity" in md_content
    assert "Model Limitations" in md_content

    # JSON checks
    json_dict = export_report_json(report)
    assert isinstance(json_dict, dict)
    assert json_dict["report_id"] == "R_TEST_001"

    # Try serialize
    serialized = json.dumps(json_dict)
    assert isinstance(serialized, str)


def test_information_leakage_constraint():
    """Verify no hidden bottleneck labels/true capacities appear in operator sections."""
    (
        nodes,
        edges,
        demands,
        bottlenecks,
        config,
        res_base,
        perturbed,
        interv,
        bench,
    ) = _setup_report_data()

    report = build_decision_report(
        nodes,
        edges,
        demands,
        config,
        benchmark_results=bench,
        baseline_result=res_base,
        perturbed_results=perturbed,
        intervention_metrics=interv,
    )

    # 1. Operators sections:
    operator_fields = [
        report.executive_summary,
        report.shadow_price_summary,
        report.scenario_comparison,
        report.intervention_recommendations,
        report.model_limitations,
    ]

    for field_str in operator_fields:
        assert "is_hidden_bottleneck" not in field_str
        assert "true_capacity" not in field_str

    # 2. Check top_bottlenecks records
    gt_bottleneck_nodes = bottlenecks[bottlenecks["is_hidden_bottleneck"]]["node_id"].tolist()
    assert len(gt_bottleneck_nodes) > 0

    for record in report.top_bottlenecks:
        assert "is_hidden_bottleneck" not in record
        assert "true_capacity" not in record

        node_id = record["node_id"]
        # If this node is actually a ground-truth bottleneck, the capacity listed
        # in the report must be the nominal/public capacity, not the true capacity.
        if node_id in gt_bottleneck_nodes:
            public_cap = nodes[nodes["node_id"] == node_id].iloc[0]["capacity"]
            true_cap = bottlenecks[bottlenecks["node_id"] == node_id].iloc[0]["true_capacity"]
            # Assert they are different in setup
            assert public_cap != true_cap
            # Assert the report capacity matches public nominal capacity
            assert record["capacity"] == public_cap
