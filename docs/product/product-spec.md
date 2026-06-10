# Technical Product Specification
## Project: Phantom Veil (Constraint Space Simulator & Clearinghouse)

---

## 1. System Architecture

Phantom Veil is a mathematical simulation and optimization suite structured into four layers:

```
+-------------------------------------------------------------+
|                     1. World Generator                      |
| (Compiles synthetic supply chain graphs with dark rules)    |
+-------------------------------------------------------------+
                              | (Saves nodes, edges, demands)
                              v
+-------------------------------------------------------------+
|                     2. Oracle Solver                        |
|                                                             |
|  [Layer 1: Time-Expanded LP] <=======> [Layer 2: Stiff ODE] |
|  (Extracts shadow prices \lambda)      (Models queue/yield) |
|                              \                              |
|                               v                             |
|                  [Layer 3: Inverse Solver]                  |
|               (Huber L1 robust reconstruction)              |
+-------------------------------------------------------------+
                              | (Outputs shadow prices & candidates)
                              v
+-------------------------------------------------------------+
|              3. Coordination & Clearinghouse                |
|  (ADMM distributed pricing & Capacity Option pricing)       |
+-------------------------------------------------------------+
                              | (Renders outputs)
                              v
+-------------------------------------------------------------+
|                     4. Streamlit UI                         |
| (Interactive sliders, PyVis graph coloring, Alpha panel)    |
+-------------------------------------------------------------+
```

---

## 2. Data Models (Schemas)

The sandbox operates on three core CSV input structures.

### 2.1. Nodes Schema (`nodes.csv`)
Defines the entities (suppliers/manufacturing lines) in the constraint space.

| Field | Type | Description |
| :--- | :--- | :--- |
| `node_id` | String (Unique) | Name of the transformation node. |
| `tier` | Integer | Supplier tier level (1 = terminal, 4 = raw/deepest). |
| `capacity` | Float | Nominal capacity per week (units). |
| `process_class` | String | e.g., `wafer_fab`, `packaging`, `die_attach`, `testing`. |
| `resource_class` | String | e.g., `machine_hour`, `adhesive`, `test_fixture`, `gas`. |
| `geographic_region` | String | e.g., `Taiwan`, `US`, `Germany`, `Singapore`. |

### 2.2. Edges Schema (`edges.csv`)
Defines the BOM relationship and physical delay between nodes.

| Field | Type | Description |
| :--- | :--- | :--- |
| `source` | String | ID of the upstream node. |
| `target` | String | ID of the downstream node. |
| `bom_ratio` | Float | Units of source required to produce 1 unit of target. |
| `transit_delay_weeks` | Integer | Transport/process lag time (delay $d_{uv}$). |

### 2.3. Demands Schema (`demands.csv`)
Defines the target SKU orders over time.

| Field | Type | Description |
| :--- | :--- | :--- |
| `sku_id` | String | ID of the terminal (Tier 1) node. |
| `week` | Integer | Time step $t \in [1, 52]$. |
| `quantity` | Float | Target output volume required. |

---

## 3. Mathematical Specifications

### 3.1. Layer 1: Time-Expanded Linear Programming (Shadow Pricing)
We map the supply chain graph $\mathcal{G} = (\mathcal{V}, \mathcal{E})$ into a time-expanded network over $t \in \{1, \dots, T\}$.

#### Variables:
* $x_{u \to v, t} \ge 0$: Flow of material from node $u$ to node $v$ shipped at week $t$.
* $I_{v, t} \ge 0$: Inventory held at node $v$ at the end of week $t$.
* $S_{v, t} \ge 0$: Shortage of SKU $v$ (only for $v \in \text{SKUs}$) at week $t$.

#### Optimization Formulation:
$$\min_{x, I, S} \sum_{t=1}^{T} \sum_{v \in \text{SKUs}} P_v \cdot S_{v, t}$$
Subject to:

1. **Flow Conservation (with BOM ratios & delays):**
   $$I_{v, t} = I_{v, t-1} + \sum_{u \in \text{Parents}(v)} x_{u \to v, t - d_{uv}} - \sum_{w \in \text{Children}(v)} \text{bom\_ratio}_{vw} \cdot x_{v \to w, t} \quad \forall v \notin \text{SKUs}$$
   $$I_{v, t} = I_{v, t-1} + \sum_{u \in \text{Parents}(v)} x_{u \to v, t - d_{uv}} - S_{v, t-1} + S_{v, t} - \text{Demand}_{v, t} \quad \forall v \in \text{SKUs}$$
   Where $d_{uv} = \text{transit\_delay\_weeks}_{uv}$. If $t - d_{uv} < 0$, the incoming flow term is $0$.

2. **Capacity Constraint:**
   $$\sum_{w \in \text{Children}(v)} x_{v \to w, t} \le C_v^{\text{effective}}(t) \quad \forall v \in \mathcal{V}, \forall t$$

#### Shadow Price Extraction:
The Lagrange multiplier associated with the capacity constraint is:
$$\lambda_v(t) = \text{Shadow Price of capacity at node } v \text{ at week } t$$
This is extracted directly from the solver using `scipy.optimize.linprog(method="highs")` via the `marginals` output fields of the constraints.

---

### 3.2. Layer 2: Continuous Stiff Queueing Dynamics & Yield Degradation
For nodes flagged as highly utilized ($\rho_v \ge 0.8$), we run a continuous-time ordinary differential equation (ODE) simulation to model local queuing dynamics and yield degradation.

#### Dynamic Equations:
1. **Queue Length ($Q_v$):**
   $$\frac{dQ_v(t)}{dt} = \Lambda_v(t) - \mu_v(t) \cdot Y_v(t)$$
   Where $\Lambda_v(t)$ is the arrival rate of orders (flow from LP), $\mu_v(t)$ is the nominal maximum service rate (nominal capacity), and $Y_v(t)$ is the instantaneous yield.
   * *Non-negativity constraint:* If $Q_v(t) = 0$, we enforce $\frac{dQ_v(t)}{dt} = \max\left(0, \Lambda_v(t) - \mu_v(t) \cdot Y_v(t)\right)$.

2. **Utilization Pressure ($\rho_v$):**
   $$\rho_v(t) = \frac{\Lambda_v(t)}{\mu_v(t) \cdot Y_v(t) + \epsilon}$$

3. **Damage / Maintenance Debt Accumulation ($D_v$):**
   $$\frac{dD_v(t)}{dt} = a \cdot \max\left(0, \rho_v(t) - \rho_{\text{safe}}\right)^p$$
   Where $\rho_{\text{safe}} \approx 0.85$ is the safety threshold, $a$ is the wear coefficient, and $p \approx 1.5$ is the non-linear scaling factor.

4. **Yield Degradation ($Y_v$):**
   $$Y_v(t) = Y_{\text{base}} \cdot \max\left(0.1, 1.0 - k \cdot D_v(t)\right)$$
   Where $k$ is the yield sensitivity parameter.

5. **Kingman Dilation Factor ($\Gamma_v$):**
   $$\Gamma_v(t) = 1.0 + \frac{\rho_v(t)^2}{2(1.0 - \rho_v(t))} \cdot \left(\frac{C_a^2 + C_s^2}{2}\right)$$
   Where $C_a^2, C_s^2$ are coefficients of variation for arrivals and service times.
   * *Stiffness handling:* If $\rho_v(t) \ge 0.98$, we cap $\Gamma_v(t) = \Gamma_{\max}$ to avoid infinity.

#### Solver Configuration:
Due to the extreme stiffness of the equations as $\rho_v \to 1$, the ODE must be solved using an implicit solver:
```python
scipy.integrate.solve_ivp(
    fun=ode_system,
    t_span=(0, T),
    y0=[Q0, D0],
    method="BDF", # Backward Differentiation Formula
    rtol=1e-6,
    atol=1e-8,
    events=[queue_collapse_event]
)
```

---

### 3.3. Layer 3: Pathological Inverse Solver (Robust Sparse Recovery)
From downstream observed lead-time dilation and price covariance residuals $y \in \mathbb{R}^M$, we reconstruct the hidden sub-tier capacity states $z \in \mathbb{R}^N$ ($N \gg M$).

#### Formulation:
$$\min_{z} \sum_{i=1}^{M} \phi_{\text{Huber}}\left(y_i - [Az]_i\right) + \lambda \|z\|_1 + \gamma z^T L z$$
Where:
* $A \in \mathbb{R}^{M \times N}$ is the sensitivity matrix propagating sub-tier delays to SKU observations.
* $\|z\|_1$ is the L1 norm to enforce **sparsity** (assuming only a few hidden constraints fail concurrently).
* $L$ is the Graph Laplacian expressing geographical or process similarity (nodes sharing resources are penalized if their failure states diverge).
* $\phi_{\text{Huber}}(r)$ is the Huber loss to handle adversarial data reporting (outliers):
  $$\phi_{\text{Huber}}(r) = \begin{cases} 
  \frac{1}{2} r^2 & \text{if } |r| \le \delta \\
  \delta(|r| - \frac{1}{2}\delta) & \text{if } |r| > \delta 
  \end{cases}$$

#### Solver Interface:
Implemented using `scipy.optimize.least_squares` with robust loss settings:
```python
scipy.optimize.least_squares(
    fun=residual_function,
    x0=z_initial,
    loss="huber",
    f_scale=delta,
    bounds=(0, 1) # Normalised capacity degradation bounds
)
```

---

### 3.4. Layer 4: Mechanism Design & Coordination

#### 1. ADMM Coordination Protocol (Distributed Optimization)
To protect proprietary cost and capacity data, the global LP can be decomposed across nodes $i \in \mathcal{V}$ using the Alternating Direction Method of Multipliers (ADMM).
* **Local Update (Node $i$):**
  $$x_i^{k+1} = \arg\min_{x_i \in \mathcal{F}_i} \left( c_i^T x_i + (\lambda^k)^T (A_i x_i - b_i) + \frac{\rho_{\text{ADMM}}}{2} \| A_i x_i + \sum_{j \neq i} A_j x_j^k - b \|^2 \right)$$
* **Global Shadow Price Update (Clearinghouse Master):**
  $$\lambda^{k+1} = \lambda^k + \rho_{\text{ADMM}} \left( \sum_{i \in \mathcal{V}} A_i x_i^{k+1} - b \right)$$
Each node $i$ solves only its local constrained domain $\mathcal{F}_i$ and communicates the marginal response vectors to the Clearinghouse Master, which updates the global shadow prices $\lambda$.

#### 2. Panic Reproduction Number ($R_p$)
To evaluate the risk of triggering defensive hoarding or supplier runs when a bottleneck is detected, we calculate:
$$R_p = \beta \cdot D_{\text{avg}} \cdot \left(1 - P_{\text{substitute}}\right)$$
Where:
* $\beta$: Transmission probability of panic between adjacent nodes in the supply chain graph.
* $D_{\text{avg}}$: Mean downstream exposure depth of the bottleneck node.
* $P_{\text{substitute}}$: Probability that downstream nodes can instantly source an alternative resource.
* **Interpretation:**
  * $R_p < 1.0$: Panic decays. Normal mitigation instructions can be communicated.
  * $R_p \ge 1.0$: Panic spreads exponentially. The system triggers **Epistemic Airgap Mode** (sends private, bilaterally decoupled mitigation playbooks instead of publishing public warnings).
