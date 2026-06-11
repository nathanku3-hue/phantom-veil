"""Decision Report Generator for Phantom Veil (MVP-005)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from phantom_veil.scenarios import ScenarioResult, compare_scenarios


@dataclass
class ReportConfig:
    """Configuration for decision report generation."""

    report_id: str
    seed: int
    top_k: int
    scenario_ids: List[str] = field(default_factory=list)
    include_benchmark_summary: bool = True
    include_intervention_summary: bool = True


@dataclass
class DecisionReport:
    """Typed decision report containing all operator-facing sections."""

    executive_summary: str
    top_bottlenecks: List[dict]
    shadow_price_summary: str
    scenario_comparison: str
    intervention_recommendations: str
    benchmark_quality: str
    model_limitations: str
    config: ReportConfig
    dynamic_risk: str = ""


def _build_exec_summary(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    config: ReportConfig,
    baseline_result: Optional[ScenarioResult],
) -> str:
    n_nodes = len(nodes)
    n_edges = len(edges)
    n_weeks = int(demands["week"].max())

    summary = (
        f"This decision report evaluates supply-chain network vulnerability "
        f"for report '{config.report_id}' (Seed: {config.seed}).\n"
        f"The network comprises {n_nodes} nodes and {n_edges} BOM relationships "
        f"across a {n_weeks}-week planning horizon."
    )
    if baseline_result is not None:
        summary += (
            f"\nUnder the baseline scenario, the total shortage across all SKUs is "
            f"{baseline_result.total_shortage:.2f} units, with an objective value "
            f"of {baseline_result.objective_value:.2f}."
        )
    else:
        summary += "\nBaseline optimization results were not provided."
    return summary


def _build_top_bottlenecks(
    nodes: pd.DataFrame,
    config: ReportConfig,
    baseline_result: Optional[ScenarioResult],
) -> List[dict]:
    if baseline_result is None or not baseline_result.top_shadow_price_nodes:
        return []

    top_nodes = baseline_result.top_shadow_price_nodes[: config.top_k]
    records = []
    for rank_idx, node_id in enumerate(top_nodes):
        node_row = nodes[nodes["node_id"] == node_id]
        if node_row.empty:
            continue
        row = node_row.iloc[0]
        records.append(
            {
                "rank": rank_idx + 1,
                "node_id": node_id,
                "tier": int(row["tier"]),
                "capacity": float(row["capacity"]),
                "process_class": str(row["process_class"]),
                "geographic_region": str(row["geographic_region"]),
            }
        )
    return records


def _build_shadow_price_summary(
    config: ReportConfig,
    baseline_result: Optional[ScenarioResult],
) -> str:
    if baseline_result is None or not baseline_result.top_shadow_price_nodes:
        return "Shadow price data is unavailable."

    top_nodes = baseline_result.top_shadow_price_nodes[: config.top_k]
    nodes_str = ", ".join(top_nodes)
    return (
        f"Vulnerability analysis identified the following top-{config.top_k} bottleneck "
        f"nodes based on peak shadow prices: {nodes_str}.\n"
        f"These nodes represent active capacity constraints where increasing capacity "
        f"would directly reduce supply chain shortages."
    )


def _build_scenario_comparison(
    baseline_result: Optional[ScenarioResult],
    perturbed_results: Optional[Dict[str, ScenarioResult]],
    config: ReportConfig,
) -> str:
    if baseline_result is None or not perturbed_results:
        return "Scenario comparison data is unavailable."

    lines = []
    for sc_id in config.scenario_ids:
        if sc_id not in perturbed_results:
            continue
        sc_res = perturbed_results[sc_id]
        diff = compare_scenarios(baseline_result, sc_res, top_k=config.top_k)
        line = (
            f"Scenario '{sc_id}': Objective Delta = {diff['objective_delta']:.2f}, "
            f"Shortage Delta = {diff['total_shortage_delta']:.2f}, "
            f"Shortage Reduction = {diff['shortage_reduction']:.2f}."
        )
        lines.append(line)

    if not lines:
        return "No matching scenarios compared."
    return "\n".join(lines)


def _build_intervention_recommendations(
    intervention_metrics: Optional[dict],
    config: ReportConfig,
) -> str:
    if not config.include_intervention_summary or intervention_metrics is None:
        return "Intervention recommendations are not included."

    base = intervention_metrics.get("baseline_shortage", 0.0)
    interv = intervention_metrics.get("intervention_shortage", 0.0)
    reduc = intervention_metrics.get("shortage_reduction", 0.0)
    added = intervention_metrics.get("total_capacity_added", 0.0)
    eff = intervention_metrics.get("reduction_per_unit_capacity", 0.0)

    return (
        f"Intervention set evaluation shows that adding {added:.2f} total units of "
        f"capacity to the top-{config.top_k} recommended bottlenecks reduced "
        f"total shortages from {base:.2f} to {interv:.2f} (a reduction of {reduc:.2f} units).\n"
        f"The intervention efficiency is {eff:.4f} units of shortage reduction per unit "
        f"capacity added."
    )


def _build_benchmark_quality(
    benchmark_results: Optional[dict],
    config: ReportConfig,
) -> str:
    if not config.include_benchmark_summary or benchmark_results is None:
        return "Benchmark quality summary is not included."

    prec = benchmark_results.get("precision@k", 0.0)
    rec = benchmark_results.get("recall@k", 0.0)
    overlap = benchmark_results.get("top_k_overlap", 0.0)
    reduction = benchmark_results.get("shortage_reduction", 0.0)

    return (
        f"Harness evaluation benchmark quality metrics (Top-{config.top_k}):\n"
        f"  - Precision@k: {prec:.4f}\n"
        f"  - Recall@k: {rec:.4f}\n"
        f"  - Top-k Overlap Count: {overlap:.2f}\n"
        f"  - Average Shortage Reduction from fixes: {reduction:.2f} units."
    )


def _build_model_limitations() -> str:
    return (
        "The time-expanded supply-chain shortage model is subject to the following limitations:\n"
        "1. Linear Optimization: Assumes perfectly divisible flows and constant cost structures.\n"
        "2. Static transit delays: Transit delay weeks are assumed constant and deterministic.\n"
        "3. Bill of Materials (BOM) ratios: Static conversion ratios are enforced "
        "without yields/scraps.\n"
        "4. Continuous queues are not integrated in the LP level; transient lead-time "
        "spikes are not modeled."
    )


def _build_dynamic_risk(
    dynamic_risk_result: Optional[Any],
) -> str:
    if dynamic_risk_result is None:
        return "Dynamic queue-dynamics risk analysis was not included."

    from phantom_veil.dynamics import summarize_dynamic_risk

    summary = summarize_dynamic_risk(dynamic_risk_result)
    lines = ["Continuous queue-dynamics simulation risk summary:"]
    for nid in dynamic_risk_result.simulated_nodes:
        m_q = summary["max_queue_by_node"][nid]
        m_u = summary["max_utilization_by_node"][nid]
        m_lt = summary["max_lead_time_multiplier_by_node"][nid]
        lines.append(
            f"  - Node {nid}: Max Queue = {m_q:.2f}, Max Utilization = {m_u:.2f}, "
            f"Max Lead-Time Multiplier = {m_lt:.2f}"
        )
    if dynamic_risk_result.warnings:
        lines.append("Warnings generated:")
        for w in dynamic_risk_result.warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("No utilization warning thresholds were exceeded.")
    return "\n".join(lines)


def build_decision_report(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    config: ReportConfig,
    benchmark_results: Optional[dict] = None,
    baseline_result: Optional[ScenarioResult] = None,
    perturbed_results: Optional[Dict[str, ScenarioResult]] = None,
    intervention_metrics: Optional[dict] = None,
    dynamic_risk_result: Optional[Any] = None,
) -> DecisionReport:
    """Build a typed DecisionReport object containing all operator sections.

    Args:
        nodes: Observed nodes DataFrame.
        edges: Edges/BOM relationships DataFrame.
        demands: Weekly demands DataFrame.
        config: ReportConfig object.
        benchmark_results: Dict containing offline benchmark scores.
        baseline_result: ScenarioResult of the baseline run.
        perturbed_results: Dict mapping scenario_id to ScenarioResult.
        intervention_metrics: Dict containing intervention effectiveness.
        dynamic_risk_result: QueueDynamicsResult of simulated dynamics.

    Returns:
        DecisionReport object.
    """
    exec_summary = _build_exec_summary(nodes, edges, demands, config, baseline_result)
    top_b = _build_top_bottlenecks(nodes, config, baseline_result)
    sp_summary = _build_shadow_price_summary(config, baseline_result)
    sc_comparison = _build_scenario_comparison(baseline_result, perturbed_results, config)
    interv_rec = _build_intervention_recommendations(intervention_metrics, config)
    bench_quality = _build_benchmark_quality(benchmark_results, config)
    limitations = _build_model_limitations()
    dyn_risk = _build_dynamic_risk(dynamic_risk_result)

    return DecisionReport(
        executive_summary=exec_summary,
        top_bottlenecks=top_b,
        shadow_price_summary=sp_summary,
        scenario_comparison=sc_comparison,
        intervention_recommendations=interv_rec,
        benchmark_quality=bench_quality,
        model_limitations=limitations,
        config=config,
        dynamic_risk=dyn_risk,
    )


def export_report_markdown(report: DecisionReport) -> str:
    """Export the DecisionReport to a formatted Markdown string.

    Args:
        report: DecisionReport to export.

    Returns:
        Markdown string.
    """
    lines = [
        f"# Decision Report: {report.config.report_id}",
        "",
        "## Executive Summary",
        report.executive_summary,
        "",
        "## Top Bottlenecks",
    ]

    if report.top_bottlenecks:
        lines.extend(
            [
                "| Rank | Node ID | Tier | Capacity | Process Class | Geographic Region |",
                "|---|---|---|---|---|---|",
            ]
        )
        for record in report.top_bottlenecks:
            cap_val = f"{record['capacity']:.2f}"
            row_str = (
                f"| {record['rank']} | {record['node_id']} | {record['tier']} | "
                f"{cap_val} | {record['process_class']} | {record['geographic_region']} |"
            )
            lines.append(row_str)
    else:
        lines.append("No bottleneck rankings available.")

    lines.extend(
        [
            "",
            "## Shadow Price Summary",
            report.shadow_price_summary,
            "",
            "## Scenario Comparison",
            report.scenario_comparison,
            "",
            "## Intervention Recommendations",
            report.intervention_recommendations,
            "",
            "## Dynamic Risk Analysis",
            report.dynamic_risk,
            "",
            "## Benchmark Quality",
            report.benchmark_quality,
            "",
            "## Model Limitations",
            report.model_limitations,
        ]
    )

    return "\n".join(lines)


def export_report_json(report: DecisionReport) -> dict:
    """Export the DecisionReport to a serializable dictionary.

    Args:
        report: DecisionReport to export.

    Returns:
        JSON-serializable dictionary.
    """
    return {
        "report_id": report.config.report_id,
        "config": {
            "report_id": report.config.report_id,
            "seed": report.config.seed,
            "top_k": report.config.top_k,
            "scenario_ids": report.config.scenario_ids,
            "include_benchmark_summary": report.config.include_benchmark_summary,
            "include_intervention_summary": report.config.include_intervention_summary,
        },
        "executive_summary": report.executive_summary,
        "top_bottlenecks": report.top_bottlenecks,
        "shadow_price_summary": report.shadow_price_summary,
        "scenario_comparison": report.scenario_comparison,
        "intervention_recommendations": report.intervention_recommendations,
        "benchmark_quality": report.benchmark_quality,
        "dynamic_risk": report.dynamic_risk,
        "model_limitations": report.model_limitations,
    }
