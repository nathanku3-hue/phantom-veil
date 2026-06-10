"""Time-expanded shortage minimization LP solver for Phantom Veil."""

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import scipy.optimize as opt
import scipy.sparse as sp

from phantom_veil.io import validate_demands, validate_edges, validate_nodes


@dataclass
class LPSolverResult:
    """Typed result object for the LP shortage solver."""

    success: bool
    objective_value: float
    status: int
    message: str
    served_demand: pd.DataFrame
    shortages: pd.DataFrame
    capacity_shadow_prices: pd.DataFrame
    raw_solver_metadata: dict


def solve_shortage_lp(
    nodes: pd.DataFrame, edges: pd.DataFrame, demands: pd.DataFrame
) -> LPSolverResult:
    """Solve the time-expanded supply-chain shortage minimization LP.

    Args:
        nodes: Public nodes DataFrame.
        edges: Edges/BOM relationships DataFrame.
        demands: Weekly demands DataFrame.

    Returns:
        LPSolverResult object.
    """
    validate_nodes(nodes)
    validate_edges(edges, nodes)
    validate_demands(demands, nodes)

    N = len(nodes)
    E = len(edges)
    W = int(demands["week"].max())

    t1_nodes = nodes[nodes["tier"] == 1]["node_id"].tolist()
    S = len(t1_nodes)

    node_id_to_idx = {row["node_id"]: idx for idx, row in nodes.iterrows()}
    sku_to_idx = {node_id: idx for idx, node_id in enumerate(t1_nodes)}

    (
        c,
        A_ub,
        b_ub,
        A_eq,
        b_eq,
        capacity_constraint_rows,
        inequality_rows_per_week,
        row_counts,
    ) = _build_lp_matrices(nodes, edges, demands, N, E, S, W, node_id_to_idx, sku_to_idx, t1_nodes)

    V = W * (N + E + 2 * S)
    bounds = [(0.0, None) for _ in range(V)]

    res = opt.linprog(
        c=c,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )

    if not res.success or res.status != 0:
        raise RuntimeError(
            f"LP Solver failed with status {res.status}: {res.message}. "
            "Please verify that the input constraints are feasible and bounded."
        )

    served_data, shortage_data = _extract_flows(res.x, W, N, E, S, t1_nodes)
    shadow_prices_data = _extract_shadow_prices(res, capacity_constraint_rows)

    metadata = {
        "nit": res.nit,
        "c": c.tolist(),
        "x": res.x.tolist(),
        "capacity_constraint_rows": capacity_constraint_rows,
        "inequality_rows_per_week": inequality_rows_per_week,
        "row_counts": row_counts,
    }

    return LPSolverResult(
        success=bool(res.success),
        objective_value=float(res.fun),
        status=int(res.status),
        message=str(res.message),
        served_demand=pd.DataFrame(served_data),
        shortages=pd.DataFrame(shortage_data),
        capacity_shadow_prices=pd.DataFrame(shadow_prices_data),
        raw_solver_metadata=metadata,
    )


def _var_index(var_type: str, index: int, week: int, N: int, E: int, S: int) -> int:
    """Helper to compute variable flat index for a given week."""
    base = week * (N + E + 2 * S)
    if var_type == "production":
        return base + index
    if var_type == "flow":
        return base + N + index
    if var_type == "served":
        return base + N + E + index
    if var_type == "shortage":
        return base + N + E + S + index
    raise ValueError(f"Invalid var_type: {var_type}")


def _add_capacity_constraints(
    nodes: pd.DataFrame,
    N: int,
    E: int,
    S: int,
    W: int,
    ub_rows: List[int],
    ub_cols: List[int],
    ub_data: List[float],
    ub_rhs: List[float],
    capacity_constraint_rows: List[dict],
    inequality_rows_per_week: Dict[int, int],
    start_row: int,
) -> int:
    """Add capacity constraints to A_ub and b_ub."""
    row_idx = start_row
    for w in range(W):
        for n in range(N):
            cap = nodes.iloc[n]["capacity"]
            ub_rows.append(row_idx)
            ub_cols.append(_var_index("production", n, w, N, E, S))
            ub_data.append(1.0)
            ub_rhs.append(cap)

            capacity_constraint_rows.append(
                {
                    "node_id": nodes.iloc[n]["node_id"],
                    "week": w + 1,
                    "row_idx": row_idx,
                    "constraint_type": "capacity",
                }
            )
            inequality_rows_per_week[w + 1] = inequality_rows_per_week.get(w + 1, 0) + 1
            row_idx += 1
    return row_idx


def _add_flow_conservation_constraints(
    nodes: pd.DataFrame,
    N: int,
    E: int,
    S: int,
    W: int,
    outgoing_edges: Dict[str, List[int]],
    ub_rows: List[int],
    ub_cols: List[int],
    ub_data: List[float],
    ub_rhs: List[float],
    inequality_rows_per_week: Dict[int, int],
    start_row: int,
) -> int:
    """Add flow conservation constraints to A_ub and b_ub."""
    row_idx = start_row
    for w in range(W):
        for n in range(N):
            node_id = nodes.iloc[n]["node_id"]
            ub_rows.append(row_idx)
            ub_cols.append(_var_index("production", n, w, N, E, S))
            ub_data.append(-1.0)
            for edge_idx in outgoing_edges[node_id]:
                ub_rows.append(row_idx)
                ub_cols.append(_var_index("flow", edge_idx, w, N, E, S))
                ub_data.append(1.0)
            ub_rhs.append(0.0)
            inequality_rows_per_week[w + 1] = inequality_rows_per_week.get(w + 1, 0) + 1
            row_idx += 1
    return row_idx


def _add_bom_constraints(
    edges: pd.DataFrame,
    N: int,
    E: int,
    S: int,
    W: int,
    node_id_to_idx: Dict[str, int],
    ub_rows: List[int],
    ub_cols: List[int],
    ub_data: List[float],
    ub_rhs: List[float],
    inequality_rows_per_week: Dict[int, int],
    start_row: int,
) -> int:
    """Add BOM transit delay constraints to A_ub and b_ub."""
    row_idx = start_row
    for w in range(W):
        for e_idx in range(E):
            edge_row = edges.iloc[e_idx]
            bom_ratio = edge_row["bom_ratio"]
            delay = int(edge_row["transit_delay_weeks"])
            target_idx = node_id_to_idx[edge_row["target"]]

            ub_rows.append(row_idx)
            ub_cols.append(_var_index("production", target_idx, w, N, E, S))
            ub_data.append(bom_ratio)

            if w - delay >= 0:
                ub_rows.append(row_idx)
                ub_cols.append(_var_index("flow", e_idx, w - delay, N, E, S))
                ub_data.append(-1.0)
                ub_rhs.append(0.0)
            else:
                ub_rhs.append(0.0)
            inequality_rows_per_week[w + 1] = inequality_rows_per_week.get(w + 1, 0) + 1
            row_idx += 1
    return row_idx


def _add_served_limits(
    t1_nodes: List[str],
    N: int,
    E: int,
    S: int,
    W: int,
    node_id_to_idx: Dict[str, int],
    ub_rows: List[int],
    ub_cols: List[int],
    ub_data: List[float],
    ub_rhs: List[float],
    inequality_rows_per_week: Dict[int, int],
    start_row: int,
) -> int:
    """Add served limits constraints to A_ub and b_ub."""
    row_idx = start_row
    for w in range(W):
        for s in range(S):
            sku_id = t1_nodes[s]
            node_idx = node_id_to_idx[sku_id]
            ub_rows.append(row_idx)
            ub_cols.append(_var_index("served", s, w, N, E, S))
            ub_data.append(1.0)
            ub_rows.append(row_idx)
            ub_cols.append(_var_index("production", node_idx, w, N, E, S))
            ub_data.append(-1.0)
            ub_rhs.append(0.0)
            inequality_rows_per_week[w + 1] = inequality_rows_per_week.get(w + 1, 0) + 1
            row_idx += 1
    return row_idx


def _add_demand_equality_constraints(
    demands: pd.DataFrame,
    t1_nodes: List[str],
    N: int,
    E: int,
    S: int,
    W: int,
    eq_rows: List[int],
    eq_cols: List[int],
    eq_data: List[float],
    eq_rhs: List[float],
) -> int:
    """Add demand satisfaction equality constraints to A_eq and b_eq."""
    row_idx = 0
    demand_dict = {(r["sku_id"], r["week"]): r["quantity"] for _, r in demands.iterrows()}
    for w in range(W):
        for s in range(S):
            sku_id = t1_nodes[s]
            qty = demand_dict.get((sku_id, w + 1), 0.0)
            eq_rows.append(row_idx)
            eq_cols.append(_var_index("served", s, w, N, E, S))
            eq_data.append(1.0)
            eq_rows.append(row_idx)
            eq_cols.append(_var_index("shortage", s, w, N, E, S))
            eq_data.append(1.0)
            eq_rhs.append(qty)
            row_idx += 1
    return row_idx


def _build_lp_matrices(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    demands: pd.DataFrame,
    N: int,
    E: int,
    S: int,
    W: int,
    node_id_to_idx: Dict[str, int],
    sku_to_idx: Dict[str, int],
    t1_nodes: List[str],
) -> Tuple[
    np.ndarray,
    sp.coo_matrix,
    np.ndarray,
    sp.coo_matrix,
    np.ndarray,
    List[dict],
    Dict[int, int],
    Dict[str, int],
]:
    """Build the constraint matrices and objective vectors for linprog."""
    G = N + E + 2 * S
    V = W * G

    c = np.zeros(V)
    for w in range(W):
        for s in range(S):
            c[_var_index("shortage", s, w, N, E, S)] = 1.0
        for n in range(N):
            c[_var_index("production", n, w, N, E, S)] = 1e-5
        for e in range(E):
            c[_var_index("flow", e, w, N, E, S)] = 1e-5

    ub_rows, ub_cols, ub_data, ub_rhs = [], [], [], []
    eq_rows, eq_cols, eq_data, eq_rhs = [], [], [], []

    capacity_constraint_rows = []
    inequality_rows_per_week = {w + 1: 0 for w in range(W)}

    outgoing_edges = {row["node_id"]: [] for _, row in nodes.iterrows()}
    for idx, row in edges.iterrows():
        outgoing_edges[row["source"]].append(idx)

    next_row = _add_capacity_constraints(
        nodes,
        N,
        E,
        S,
        W,
        ub_rows,
        ub_cols,
        ub_data,
        ub_rhs,
        capacity_constraint_rows,
        inequality_rows_per_week,
        0,
    )

    next_row = _add_flow_conservation_constraints(
        nodes,
        N,
        E,
        S,
        W,
        outgoing_edges,
        ub_rows,
        ub_cols,
        ub_data,
        ub_rhs,
        inequality_rows_per_week,
        next_row,
    )

    next_row = _add_bom_constraints(
        edges,
        N,
        E,
        S,
        W,
        node_id_to_idx,
        ub_rows,
        ub_cols,
        ub_data,
        ub_rhs,
        inequality_rows_per_week,
        next_row,
    )

    next_row = _add_served_limits(
        t1_nodes,
        N,
        E,
        S,
        W,
        node_id_to_idx,
        ub_rows,
        ub_cols,
        ub_data,
        ub_rhs,
        inequality_rows_per_week,
        next_row,
    )

    eq_row_count = _add_demand_equality_constraints(
        demands, t1_nodes, N, E, S, W, eq_rows, eq_cols, eq_data, eq_rhs
    )

    A_ub = sp.coo_matrix((ub_data, (ub_rows, ub_cols)), shape=(next_row, V))
    A_eq = sp.coo_matrix((eq_data, (eq_rows, eq_cols)), shape=(eq_row_count, V))

    row_counts = {
        "capacity": W * N,
        "flow_conservation": W * N,
        "bom_input": W * E,
        "served_limit": W * S,
        "demand_equality": W * S,
    }

    return (
        c,
        A_ub,
        np.array(ub_rhs),
        A_eq,
        np.array(eq_rhs),
        capacity_constraint_rows,
        inequality_rows_per_week,
        row_counts,
    )


def _extract_flows(
    x: np.ndarray, W: int, N: int, E: int, S: int, t1_nodes: List[str]
) -> Tuple[List[dict], List[dict]]:
    """Extract served demand and shortages lists from LP solution."""
    served_data = []
    shortage_data = []

    for w in range(W):
        for s in range(S):
            sku_id = t1_nodes[s]
            served_val = x[_var_index("served", s, w, N, E, S)]
            shortage_val = x[_var_index("shortage", s, w, N, E, S)]

            served_data.append(
                {
                    "sku_id": sku_id,
                    "week": w + 1,
                    "quantity": round(float(served_val), 4),
                }
            )
            shortage_data.append(
                {
                    "sku_id": sku_id,
                    "week": w + 1,
                    "quantity": round(float(shortage_val), 4),
                }
            )

    return served_data, shortage_data


def _extract_shadow_prices(res: opt.OptimizeResult, row_map: List[dict]) -> List[dict]:
    """Extract and convert capacity constraint marginals (shadow prices)."""
    shadow_prices_data = []

    marginals = None
    if res.ineqlin is not None and res.ineqlin.marginals is not None:
        marginals = res.ineqlin.marginals

    for entry in row_map:
        row_idx = entry["row_idx"]
        node_id = entry["node_id"]
        week = entry["week"]

        raw_marg = float(marginals[row_idx]) if marginals is not None else 0.0

        # Sign convention: capacity_shadow_value = -raw_marginal
        shadow_val = -raw_marg

        shadow_prices_data.append(
            {
                "node_id": node_id,
                "week": week,
                "raw_marginal": round(raw_marg, 6),
                "capacity_shadow_value": round(shadow_val, 6),
            }
        )

    return shadow_prices_data
