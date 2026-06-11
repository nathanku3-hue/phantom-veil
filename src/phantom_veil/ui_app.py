"""Streamlit Interactive UI Shell for Phantom Veil (MVP-009)."""

import pandas as pd

from phantom_veil.coordination import (
    CoordinationConfig,
    evaluate_coordination_benefits,
    run_admm_coordination_smoke,
)
from phantom_veil.dynamics import (
    QueueDynamicsConfig,
    simulate_queue_dynamics,
    summarize_dynamic_risk,
)
from phantom_veil.inverse import InverseConfig, build_inverse_features, rank_inverse_bottlenecks
from phantom_veil.reporting import ReportConfig, build_decision_report, export_report_markdown
from phantom_veil.scenarios import ScenarioSpec, run_scenario
from phantom_veil.solver import solve_shortage_lp
from phantom_veil.worldgen import generate_world


def _compute_node_sensitivities(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    res_base,
    spec_base: ScenarioSpec,
) -> tuple:
    """Compute shortage deltas and intervention efficiencies for each node."""
    scenario_shortage_deltas = {}
    intervention_efficiencies = {}

    for node_id in nodes["node_id"]:
        spec_node = ScenarioSpec(
            scenario_id=f"shock_{node_id}",
            capacity_multiplier_by_node={node_id: 0.5},
        )
        res_node = run_scenario(nodes, edges, demands, spec_node)
        scenario_shortage_deltas[node_id] = res_node.total_shortage - res_base.total_shortage

        nodes_node = nodes.copy()
        nodes_node.loc[nodes_node["node_id"] == node_id, "capacity"] += 50.0
        res_node_int = run_scenario(nodes_node, edges, demands, spec_base)
        reduction = max(0.0, res_base.total_shortage - res_node_int.total_shortage)
        intervention_efficiencies[node_id] = reduction / 50.0

    return scenario_shortage_deltas, intervention_efficiencies


def run_ui_pipeline(
    seed: int,
    node_count: int,
    horizon_weeks: int,
    demand_multiplier: float,
    top_k: int,
) -> dict:
    """Deterministic pipeline helper used by the UI app.

    Consumes only public signals, keeping hidden bottleneck labels and true capacities
    out of the returned operator-facing results.
    """
    nodes, edges, demands, _ = generate_world(
        seed=seed, node_count=node_count, horizon_weeks=horizon_weeks
    )

    lp_res = solve_shortage_lp(nodes, edges, demands)

    spec_base = ScenarioSpec(scenario_id="base")
    res_base = run_scenario(nodes, edges, demands, spec_base)

    spec_shock = ScenarioSpec(
        scenario_id="shock",
        demand_multiplier=demand_multiplier,
        weeks=list(range(1, horizon_weeks + 1)),
    )
    res_shock = run_scenario(nodes, edges, demands, spec_shock)

    deltas, efficiencies = _compute_node_sensitivities(nodes, edges, demands, res_base, spec_base)

    dyn_config = QueueDynamicsConfig(horizon_days=15, top_k=top_k)
    dyn_res = simulate_queue_dynamics(nodes, edges, demands, res_base, dyn_config)
    dyn_summary = summarize_dynamic_risk(dyn_res)

    features = build_inverse_features(
        nodes=nodes,
        capacity_shadow_prices=lp_res.capacity_shadow_prices,
        scenario_shortage_deltas=deltas,
        intervention_efficiencies=efficiencies,
        dynamic_utilizations=dyn_summary["max_utilization_by_node"],
        dynamic_lead_time_multipliers=dyn_summary["max_lead_time_multiplier_by_node"],
    )

    inv_config = InverseConfig(top_k=top_k)
    inv_res = rank_inverse_bottlenecks(features, inv_config)

    coord_config = CoordinationConfig(top_k=top_k, capacity_step_limit=50.0)
    coord_res = run_admm_coordination_smoke(nodes, inv_res.ranked_nodes, features, coord_config)
    coord_benefits = evaluate_coordination_benefits(nodes, edges, demands, coord_res)

    report_config = ReportConfig(
        report_id=f"REP_SEED_{seed}",
        seed=seed,
        top_k=top_k,
        scenario_ids=["shock"],
    )
    report = build_decision_report(
        nodes=nodes,
        edges=edges,
        demands=demands,
        config=report_config,
        baseline_result=res_base,
        perturbed_results={"shock": res_shock},
        intervention_metrics=coord_benefits,
        dynamic_risk_result=dyn_res,
    )

    return {
        "top_shadow_price_nodes": res_base.top_shadow_price_nodes[:top_k],
        "inverse_ranked_nodes": inv_res.ranked_nodes,
        "base_shortage": res_base.total_shortage,
        "shock_shortage": res_shock.total_shortage,
        "shortage_delta": res_shock.total_shortage - res_base.total_shortage,
        "coordination_recommendations": coord_res.recommended_capacity_add_by_node,
        "coordination_benefits": coord_benefits,
        "markdown_report": export_report_markdown(report),
    }


def main():
    """Entry point for the Streamlit dashboard."""
    try:
        import streamlit as st
    except ImportError:
        import sys

        print("Streamlit is not installed. Please install with: pip install -e .[ui]")
        sys.exit(1)

    st.set_page_config(page_title="Phantom Veil Dashboard", layout="wide")
    st.title("🌌 Phantom Veil: Constraint Space Simulator & Clearinghouse")

    st.sidebar.header("Configuration & Inputs")
    seed = st.sidebar.number_input("Random Seed", value=42, step=1)
    node_cnt = st.sidebar.number_input("Node Count", value=10, step=1, min_value=5, max_value=100)
    weeks = st.sidebar.number_input("Horizon Weeks", value=5, step=1, min_value=2, max_value=52)
    mult = st.sidebar.slider("Demand Multiplier (Shock)", 1.0, 5.0, 2.0, 0.1)
    top_k = st.sidebar.number_input("Top K Bottlenecks", value=2, min_value=1, max_value=10)

    if st.sidebar.button("Run Simulation"):
        st.subheader("Processing Simulation Pipeline...")
        with st.spinner("Solving LP, integrating ODEs, and running ADMM coordination..."):
            res = run_ui_pipeline(
                seed=seed,
                node_count=node_cnt,
                horizon_weeks=weeks,
                demand_multiplier=mult,
                top_k=top_k,
            )

        st.success("Simulation Complete!")

        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="Baseline Shortage", value=f"{res['base_shortage']:.2f}")
            st.metric(label="Shocked Shortage", value=f"{res['shock_shortage']:.2f}")
            st.metric(label="Shortage Delta", value=f"{res['shortage_delta']:.2f}")

            st.write("### 🚨 Top Bottlenecks by LP Shadow Price")
            st.table(pd.DataFrame(res["top_shadow_price_nodes"], columns=["Node ID"]))

            st.write("### 🔍 Inverse-Ranked Bottleneck Candidates")
            st.table(pd.DataFrame(res["inverse_ranked_nodes"], columns=["Node ID"]))

        with col2:
            st.write("### 🤝 ADMM Coordination Capacity Recommendations")
            recs = res["coordination_recommendations"]
            df_recs = pd.DataFrame(
                list(recs.items()), columns=["Node ID", "Recommended Capacity Add"]
            )
            st.table(df_recs)

            st.write("### 📈 Coordination Benefits Summary")
            b = res["coordination_benefits"]
            st.write(f"- **Baseline Shortage:** {b['baseline_shortage']:.2f}")
            st.write(f"- **Coordination Shortage:** {b['coordination_shortage']:.2f}")
            st.write(f"- **Shortage Reduction:** {b['shortage_reduction']:.2f}")
            st.write(f"- **Total Capacity Added:** {b['total_capacity_added']:.2f}")
            st.write(f"- **Reduction per Unit Capacity:** {b['reduction_per_unit_capacity']:.4f}")

        st.write("---")
        st.write("## 📋 Generated Decision Report")
        st.markdown(res["markdown_report"])


if __name__ == "__main__":
    main()
