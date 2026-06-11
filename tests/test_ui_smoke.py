"""Smoke and determinism tests for the Streamlit UI module (MVP-009)."""

from phantom_veil.ui_app import run_ui_pipeline


def test_ui_import_smoke():
    """Verify that ui_app module can be imported without launching a server or failing."""
    import phantom_veil.ui_app

    assert hasattr(phantom_veil.ui_app, "run_ui_pipeline")
    assert hasattr(phantom_veil.ui_app, "main")


def test_ui_pipeline_determinism_and_no_leakage():
    """Verify run_ui_pipeline returns deterministic results and has no hidden labels leakage."""
    res1 = run_ui_pipeline(
        seed=42,
        node_count=10,
        horizon_weeks=5,
        demand_multiplier=2.0,
        top_k=2,
    )
    res2 = run_ui_pipeline(
        seed=42,
        node_count=10,
        horizon_weeks=5,
        demand_multiplier=2.0,
        top_k=2,
    )

    # 1. Assert determinism
    assert res1["top_shadow_price_nodes"] == res2["top_shadow_price_nodes"]
    assert res1["inverse_ranked_nodes"] == res2["inverse_ranked_nodes"]
    assert res1["base_shortage"] == res2["base_shortage"]
    assert res1["shock_shortage"] == res2["shock_shortage"]
    assert res1["shortage_delta"] == res2["shortage_delta"]
    assert res1["coordination_recommendations"] == res2["coordination_recommendations"]
    assert res1["coordination_benefits"] == res2["coordination_benefits"]
    assert res1["markdown_report"] == res2["markdown_report"]

    # 2. Assert no leakage of private labels or true capacity in the returned results
    for key, val in res1.items():
        if isinstance(val, str):
            assert "is_hidden_bottleneck" not in val
            assert "true_capacity" not in val
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    assert "is_hidden" not in item.lower()
        elif isinstance(val, dict):
            for k_sub, v_sub in val.items():
                assert "is_hidden" not in str(k_sub).lower()
                assert "true_capacity" not in str(k_sub).lower()
                assert "is_hidden" not in str(v_sub).lower()
                assert "true_capacity" not in str(v_sub).lower()
