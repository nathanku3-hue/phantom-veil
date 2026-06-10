# Product Requirements Document (PRD)
## Project: Phantom Veil (Constraint Space Simulator & Clearinghouse)

---

## 1. Executive Summary

Phantom Veil is a next-generation, physics-informed B2B decision-support and pricing engine for deep-tier supply chains. It identifies hidden, low-visibility, high-impact constraints (referred to as **"phantom bottlenecks"**) in Tier-3 and Tier-4 supplier networks under extreme demand shocks. By combining time-expanded linear programming, stiff ordinary differential equations (ODEs) representing queueing theory, and robust inverse solvers, Phantom Veil translates micro-level capacity limits and supply chain friction into macroeconomic risk assessments and fair-value capacity options.

---

## 2. Problem Statement

Modern global supply chain management suffers from three systemic vulnerabilities:

1. **The Dark Supply Chain (Lack of Deep-Tier Visibility):** Enterprise visibility typically stops at Tier-1 and Tier-2 suppliers. Critical dependencies (e.g., specialized testing fixtures, packaging adhesives, high-purity gases) reside in Tier-3 and Tier-4. Disruptions at these deep levels are invisible until terminal assembly lines halt.
2. **The Non-Linear Time Dilation Trap:** Traditional planners use static lead times and linear summation. In reality, as a node's capacity utilization ($\rho$) approaches 100%, queueing theory dictates that lead times explode non-linearly. Standard supply chain software fails to model this asymptotic delay.
3. **The Information Asymmetry & "Lying Supplier" Problem:** Suppliers frequently overstate capacity or understate lead times to secure contracts. When a demand shock hits, suppliers ration capacity arbitrarily, reporting false delivery estimates to avoid penalties. Passive tracking tools cannot detect these strategic distortions.
4. **Epistemic Trap in Simulation Validation:** Traditional simulation platforms rely on synthetic data containing pre-programmed bottlenecks. A model that merely uncovers what its creator hand-coded is a "tautology." Phantom Veil must prove its value by solving blind adversarial scenarios generated dynamically.

---

## 3. Product Vision & Value Proposition

* **Vision:** To transition supply chain risk management from reactive warning dashboards to active, privacy-preserving **Capacity Option Clearinghouses**.
* **Value Proposition:** 
  * **For Manufacturers:** Prevent multi-million dollar revenue losses by identifying deep-tier bottlenecks 3 to 12 months in advance, receiving actionable private mitigation playbooks.
  * **For Strategic Procurement:** Calculate the exact fair value of purchasing redundant capacity (Capacity Options) to hedge risk.
  * **For Quant Funds:** Extract alpha by predicting supply chain phase transitions and earnings shocks before they materialize in financial markets.

---

## 4. User Personas

### 4.1. Director of Strategic Sourcing (Hyperscaler/Tech OEM)
* **Needs:** Needs to know if their 800G optical transceiver suppliers or CoWoS packaging partners can meet a 5x surge in quarterly demand.
* **Pain Points:** Suppliers promise 100% fulfillment, but historical deliveries show massive variances. Traditional dashboards only show past delay statistics, not future bottleneck risk.

### 4.2. Supply Chain Risk Analyst
* **Needs:** Wants to run stress tests (e.g., "what happens if a Tier-3 chemical supplier in Taiwan has a 3% yield drop due to water shortages?").
* **Pain Points:** No tooling exists to translate a micro-level chemical yield collapse into a terminal SKU delivery delay.

### 4.3. Quantitative Portfolio Manager (Hardware & Semiconductors)
* **Needs:** Identify structural capacity limits of sub-tier vendors to predict supply constraint-induced revenue bottlenecks of major public tech companies.
* **Pain Points:** Lacks access to direct supply chain telemetry, relying on noisy, lagged corporate earnings transcripts.

---

## 5. Target Verticals

Phantom Veil prioritizes high-complexity, high-growth hardware verticals where:
* Supply chains are deep, specialized, and highly consolidated.
* Qualification of new suppliers takes months (long qualification delay).
* Demand is highly volatile and driven by technology super-cycles.

**Initial Target Sectors:**
* **AI Compute Infrastructure:** High Bandwidth Memory (HBM), CoWoS Advanced Packaging, CPO (Co-packaged Optics).
* **Optical Communications:** 800G and 1.6T DR8/FR4 optical transceiver modules.
* **Advanced Automotive:** Automotive MCUs, LiDAR optical alignment sub-assemblies.

---

## 6. Functional Requirements (MVP Surface)

The MVP must implement the following core capabilities:

### F001: Adversarial World Generator
* The system must dynamically generate random, industrially-coherent supply chain networks.
* **Constraint Grammar:** Network generation must be governed by rules defining Product Families, Process Classes (e.g., wafer fabrication, advanced packaging), Resource Classes (machine-hours, adhesives, test fixtures), and Dark Constraints (export controls, sole-source locks).
* **Blind Testing Mode:** The generator must isolate the benchmark answers from the Oracle solver to ensure blind verification (preventing the "epistemic trap").

### F002: Oracle Engine
* **Shadow Price LP Solver:** The system must solve a time-expanded flow network and extract Lagrange multipliers (Shadow Prices $\lambda$) for each constraint.
* **Stiff Dynamics Queue Simulator:** The system must model continuous queue lengths ($Q_t$) and utilization ($\rho_t$). It must couple queue delays with a sigmoid degradation curve representing yield collapse under high utilization.
* **Implicit ODE Integration:** The simulation must use implicit ODE integration (BDF or Radau) to prevent numerical divergence when utilization approaches 1.0.
* **Huber Robust Inverse Solver:** The system must take noisy, partial downstream lead-time signals and reconstruct the deep-tier hidden constraints, using L1 regularization to assume a sparse failure distribution and Huber robust loss to filter adversarial reporting noise.

### F003: Capacity Option Pricing & Mitigation
* The system must compute the fair value of expanding capacity at any bottleneck node by calculating the marginal reduction in total system shortage cost (using finite-difference validation).
* The system must generate a mitigation playbook recommendation rather than a public named warning (to prevent panic-driven supply runs, monitored via the Panic Reproduction Number $R_p$).

### F004: Interactive Dashboard UI
* The user interface must be implemented in Streamlit.
* **Interactive Sliders:** Allow users to adjust the terminal demand shock factor (1x to 10x) and sub-tier supplier yield shifts.
* **Visual Graph Rendering:** Render the supply chain network (using PyVis/Plotly) where nodes change color (green, yellow, red) based on utilization and queue dilation.
* **Alpha Insights Panel:** Display the top bottleneck constraints by shadow price, fair value of capacity options, and recommended action steps.

---

## 7. Non-Functional Requirements

* **Local Compute Boundary:** The MVP must run completely locally on a standard developer laptop. Solving a 50-node network over a 52-week time horizon must take less than 10 seconds.
* **Mathematical Sanity:** The solver must enforce strict non-negativity on queues ($Q(t) \ge 0$) via numerical projections and event triggers.
* **Data Security & Privacy:** The mathematical design must support future decentralized solving (ADMM) where suppliers only exchange shadow price vectors ($\lambda$) and marginal responses, never exposing their private cost structures or internal topologies.

---

## 8. Success Metrics

1. **Identification Accuracy (Recall):** The Oracle Engine must successfully identify the correct Tier-3/Tier-4 bottleneck in at least 85% of blind adversarial synthetic scenarios.
2. **False Alarm Rate:** The Oracle Engine must remain silent (no bottleneck detected) in null-scenarios where demand shocks do not exceed capacity thresholds.
3. **Solver Stability:** 0% integration failures (divergence or time-step freeze) when simulating extreme capacity collapse ($\rho \ge 0.98$).
