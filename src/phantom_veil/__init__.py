"""Phantom Veil package exports."""

from phantom_veil.benchmark import (
    rank_bottlenecks_by_shadow_price,
    run_benchmark_suite,
    score_predictions,
)
from phantom_veil.io import load_world, save_world, validate_demands, validate_edges, validate_nodes
from phantom_veil.reporting import (
    DecisionReport,
    ReportConfig,
    build_decision_report,
    export_report_json,
    export_report_markdown,
)
from phantom_veil.scenarios import (
    ScenarioResult,
    ScenarioSpec,
    apply_scenario,
    compare_scenarios,
    evaluate_intervention_set,
    run_scenario,
)
from phantom_veil.solver import LPSolverResult, solve_shortage_lp
from phantom_veil.worldgen import generate_world

__all__ = [
    "generate_world",
    "save_world",
    "load_world",
    "validate_nodes",
    "validate_edges",
    "validate_demands",
    "solve_shortage_lp",
    "LPSolverResult",
    "score_predictions",
    "rank_bottlenecks_by_shadow_price",
    "run_benchmark_suite",
    "ScenarioSpec",
    "ScenarioResult",
    "apply_scenario",
    "run_scenario",
    "compare_scenarios",
    "evaluate_intervention_set",
    "ReportConfig",
    "DecisionReport",
    "build_decision_report",
    "export_report_markdown",
    "export_report_json",
]
