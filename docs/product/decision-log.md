# Architectural Decision Log
## Project: Phantom Veil (Constraint Space Simulator & Clearinghouse)

This document records the architectural and design decisions for Phantom Veil, using the original conceptual dialogues as the source of truth.

---

## D001: Custom NumPy/SciPy Engine over Off-the-Shelf Simulators

### Status
Approved.

### Date
2026-06-10

### Decision
The core simulation, optimization, and inverse solver engines will be custom-built using standard numerical libraries: `NumPy`, `Pandas`, `NetworkX`, and `SciPy`. Off-the-shelf discrete event simulation (DES) frameworks (like `SimPy`), inventory management platforms (like `Stockpyl`), or system dynamics tools (like `PySD`) are rejected as primary engines and may only be used for external validation and sandbox benchmarking.

### Rationale
Discrete event simulations and generic dynamic tools encapsulate system sensitivity details (such as the Jacobian matrix, dual variables, and state gradients) in a procedural black box. To price capacity options and solve the pathological inverse problem (reconstructing Tier-4 bottlenecks from Tier-1 observations), we need direct access to:
1. Linear programming marginals (Lagrange multipliers).
2. The continuous sensitivity matrix of time delays relative to capacity changes.
3. Custom non-linear coupling of queues, yield, and damage accumulation.
Building on top of generic engines would conceal the mathematical structure required for these features.

---

## D002: LP Shadow Pricing for Capacity Option Valuation

### Status
Approved.

### Date
2026-06-10

### Decision
We use a time-expanded linear program solved via `scipy.optimize.linprog(method="highs")` to schedule flows, minimize shortages, and directly extract Lagrange multipliers ($\lambda_v(t)$) for all capacity constraints. 

### Rationale
Shadow prices represent the exact marginal utility of adding one unit of capacity to a bottleneck constraint at a specific week. By multiplying the shadow price by the probability of shock events, we can calculate the mathematically sound fair-value cap of Capacity Options (hedging contracts). We validate these shadow prices using a finite-difference sanity check:
$$\text{Marginal Impact} \approx Loss(C_v + \Delta C) - Loss(C_v)$$
This ensures mathematical alignment between the primal shortage objective and the dual constraint pricing.

---

## D003: Implicit Solvers (BDF/Radau) for Stiff Queueing Dynamics

### Status
Approved.

### Date
2026-06-10

### Decision
For high-utilization nodes ($\rho_v \ge 0.8$), we run a continuous-time queueing ODE. We solve this ODE system using `scipy.integrate.solve_ivp` with implicit Backward Differentiation Formula (`method="BDF"`) or `Radau` if BDF exhibits numerical instability. Explicit solvers (such as standard Runge-Kutta `RK45` or Euler integration) are prohibited for the final model.

### Rationale
When a supply chain node's utilization $\rho$ approaches 1.0, Kingman's queue approximation dictates that queue length and lead times blow up asymptotically. This introduces extreme mathematical stiffness into the ODE system. Explicit solvers attempt to maintain stability by shrinking the integration time step toward zero, causing the simulator to freeze, hang, or diverge. Implicit methods (BDF/Radau) are numerically stable under stiffness and guarantee completion.

---

## D004: Blind Adversarial World Generation (Anti-Tautology)

### Status
Approved.

### Date
2026-06-10

### Decision
The sandbox is split into two isolated modules:
1. **World Generator:** Generates random, industrially valid supply chain graphs governed by a constraint grammar (Resource classes, Process classes, Dark constraints).
2. **Oracle Solver:** Restricted to observing only downstream terminal signals and public nodes.
The solver must identify the bottleneck without having access to the generation seed or the ground-truth hidden labels.

### Rationale
Creating synthetic data where the designer manually specifies a bottleneck (e.g. "Tier 4 F2 Adhesive has 50% capacity") and then showing that the model finds it is an epistemic trap. It is a script playback rather than an evaluation. Blind adversarial testing evaluates the engine's ability to uncover unexpected, emergent bottlenecks under random, multi-variable shocks.

---

## D005: Robust Huber Loss & L1 Sparse Regularization for Inverse Solving

### Status
Approved.

### Date
2026-06-10

### Decision
Identifying deep-tier bottlenecks from sparse, noisy downstream signals is modeled as a sparse robust recovery problem solved via `scipy.optimize.least_squares` with `loss="huber"`. The objective function combines:
1. An L1 norm regularization term to enforce sparsity (assuming few bottlenecks occur simultaneously).
2. A Graph Laplacian term to incorporate process/geographic correlations.
3. A Huber robust loss function to filter adversarial reporting noise.

### Rationale
Reconstructing deep constraints from surface outputs is a pathologically ill-posed inverse problem (many hidden nodes, few observations). L1 regularization acts as Ockham's razor, preventing the solver from scattering degradation across all nodes. Huber loss prevents outlier noise—such as a supplier reporting false capacity values to gain leverage—from distorting the bottleneck ranking.

---

## D006: Decentralized Privacy-Preserving Coordination via ADMM

### Status
Approved.

### Date
2026-06-10

### Decision
The system architecture is designed to support the Alternating Direction Method of Multipliers (ADMM) as the coordination mechanism for multi-supplier network optimization.

### Rationale
In real-world supply chains, Tier-3 and Tier-4 suppliers treat their capacities, margins, and yield rates as proprietary trade secrets. They will refuse to upload this data to a centralized database. Under ADMM, the central clearinghouse (Oracle) acts as a coordinator that only broadcasts shadow price vectors ($\lambda$). Individual suppliers solve local optimizations on their private computers and return marginal capacity responses. The global optimum is achieved iteratively without exposing raw private data.

---

## D007: Panic-Resistant Mitigation Playbooks (Defensive Oracle)

### Status
Approved.

### Date
2026-06-10

### Decision
The engine monitors the Panic Reproduction Number ($R_p$). If $R_p \ge 1.0$, the clearinghouse enters **Epistemic Airgap Mode**. Instead of broadcasting a public alert (e.g., "Supplier A is failing"), the system generates decoupled, bilateral mitigation instructions (e.g., "Qualify alternative Material B immediately").

### Rationale
According to the Diamond-Dybvig bank run model, broadcasting a public warning about capacity shortages triggers panic-buying and defensive hoarding by downstream buyers. This hoarding immediately drains any remaining capacity, causing the exact supply chain collapse the warning was trying to prevent (a self-fulfilling prophecy). Decoupled mitigation playbooks guide users to hedge risk without triggering systemic panic runs.
