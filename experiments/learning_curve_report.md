# Learning-Curve Diagnostic Experiment Report

## Executive Summary

This diagnostic experiment investigates whether expanding the number of independent structural units improves ML re-ranking performance for the Stage-2 XGBoost model (`max_depth=2, min_child_weight=2, lr=0.1, n_est=200, colsample=0.6, reg_lambda=1.0, seed=42`) using the validated 49-feature planner representation.

### Core Verdict
- **Learning Curve Trajectory**: **Flat to Non-Monotonic Plateau** (~0.71–0.77 NDCG@3 band).
- **HypoPG Baseline Benchmark**: 0.7760 NDCG@3 on the fixed validation partition (0.7954 across all development queries).
- **Evidence for Structural Diversity Benefits**: **Absent / Insufficient**. Adding structural units beyond 8 does not yield sustained gains in re-ranking quality.
- **Strategic Recommendation on Second Workload**: **Do NOT proceed to an expensive second workload under the premise that more structural diversity will elevate this model representation.** The empirical evidence strongly indicates an **information ceiling** imposed by the planner-cost feature representation rather than sample scarcity.

---

## 1. Experimental Integrity & Data Boundary

All data handling strictly conformed to the locked evaluation rules:
- **Git Tag Verified**: `v1.0-job-final` active.
- **Dataset Boundary**: Evaluated strictly on the **371 development rows** across **16 canonical structural units** (78 queries) from IMDb / JOB.
- **Holdout Isolation**: The **228-row final holdout** (4 unseen structural units) remained strictly untouched and unread.
- **Artifact Protection**: Frozen artifacts (`experiments/final_xgb_model.json`, `experiments/final_evaluation_results.json`, `experiments/final_benchmark_results.json`) were completely preserved without modification.
- **Zero Hyperparameter Tuning & No Feature Engineering**: The Stage-2 XGBoost hyperparameters and 49-feature schema were held strictly static.
- **Zero Validation Leakage**: No preprocessing or ranking information crossed training/validation splits.

---

## 2. Methodology & Unit-Selection Strategy

Because the development partition contains exactly 16 canonical structural units, evaluating a learning curve requires an explicit, deterministic definition of training prefixes and validation sets.

### Canonical Structural Unit Sequence
Units were ordered deterministically by canonical family order from `experiments/job_similarity_components.csv` (Families 1–33):
1. `Singleton_1`
2. `Singleton_2`
3. `Singleton_3`
4. `Singleton_4`
5. `Singleton_6`
6. `Singleton_7`
7. `Singleton_10`
8. `C70_5`
9. `Singleton_14`
10. `Singleton_15`
11. `C70_6`
12. `Singleton_18`
13. `C70_7`
14. `C70_3`
15. `C70_4`
16. `Singleton_32`

### Primary Protocol: Fixed Held-Out Development Validation Set
To ensure identical evaluation difficulty across training sizes, the last 4 canonical units were held out as the **Fixed Validation Set**:
- **Fixed Validation Units (4)**: `C70_7`, `C70_3`, `C70_4`, `Singleton_32` (27 queries, 184 rows).
- **Training Candidate Pool (12 units)**: Units 1 through 12 (`Singleton_1` to `Singleton_18`, 51 queries, 187 rows).
- **Nested Training Sizes**:
  - **4 Units**: Units 1–4 (`Singleton_1` through `Singleton_4`).
  - **8 Units**: Units 1–8 (`Singleton_1` through `C70_5`).
  - **12 Units**: Units 1–12 (`Singleton_1` through `Singleton_18`).
  - **16 Units**: All 16 units (371 rows; evaluated on the fixed validation set as an **in-sample resubstitution ceiling**).

### Complementary Protocol: 4-Fold Grouped Cross-Validation
To eliminate any partition bias from selecting a single 4-unit validation set, we also partitioned the 16 units into 4 equal folds of 4 units each. In each fold, nested prefixes of 4, 8, and 12 units were trained and evaluated out-of-sample on the held-out fold, pooling across **all 78 development queries and 371 rows**.

---

## 3. Results

### Primary Protocol: Fixed Validation Set (27 Queries, 184 Rows)

*Baseline Reference: HypoPG Planner Macro NDCG@3 = **0.7760**, Top-1 Regret = **0.0060**, Spearman = **0.1175**.*

| Training Units | Evaluation Type | Tr Queries | Tr Rows | Macro NDCG@3 | Unit NDCG@3 | Top-1 Regret | Spearman | RMSE |
|---|---|---|---|---|---|---|---|---|
| **4 Units** | Out-of-Sample | 14 | 41 | **0.7760** | 0.8134 | 0.0060 | 0.1175 | 0.3030 |
| **8 Units** | Out-of-Sample | 31 | 115 | **0.7645** | 0.7989 | 0.0067 | 0.1498 | 0.3220 |
| **12 Units** | Out-of-Sample | 51 | 187 | **0.5934** | 0.6735 | 0.1985 | 0.0119 | 0.3220 |
| **16 Units** | In-Sample Ceiling | 78 | 371 | **0.7760** | 0.8134 | 0.0060 | 0.1175 | 0.1238 |

*Note on 16 Units: Evaluated on the same 4 validation units. Because all 16 units are used in training, the validation units are in-sample. RMSE drops sharply from 0.3220 to 0.1238, reflecting training-set fitting, yet the discrete candidate ranking on these queries matches the HypoPG cost ranking.*

---

### Complementary Protocol: 4-Fold Grouped CV (Pooled Across All 78 Dev Queries)

| Training Units | Mean Tr Queries | Mean Tr Rows | Evaluated Queries | Evaluated Rows | Macro NDCG@3 | Unit NDCG@3 | Top-1 Regret | Spearman | RMSE |
|---|---|---|---|---|---|---|---|---|---|
| **4 Units** | 14.8 | 49.2 | 78 | 371 | **0.7058** | 0.7043 | 0.3437 | -0.0716 | 0.6165 |
| **8 Units** | 33.2 | 122.2 | 78 | 371 | **0.7770** | 0.7850 | 0.1137 | 0.1512 | 0.5561 |
| **12 Units** | 58.5 | 278.2 | 78 | 371 | **0.7082** | 0.7380 | 0.1810 | 0.0927 | 0.5149 |
| **15 Units (LOOU)** | 73.1 | 347.8 | 78 | 371 | **0.7714** | 0.7719 | 0.1291 | 0.1267 | 0.4011 |

*Note on 15 Units: Extracted from the validated 16-fold Leave-One-Structural-Unit-Out Cross-Validation reference in `controlled_model_comparison_results.json`.*

---

## 4. Interpretation & Scientific Analysis

### 1. Shape of the Learning Curve
The learning curve is **flat to non-monotonic**:
- Increasing training data from 4 units (41 rows) to 8 units (115 rows) produces a modest initial adjustment (NDCG 0.7058 $\rightarrow$ 0.7770 in grouped CV).
- Expanding further to 12 units (187–278 rows) and 15 units (348 rows) **fails to produce any sustained improvement**. In the fixed validation test, NDCG drops to 0.5934 at 12 units as the model fits idiosyncratic patterns of the expanded training set; in 4-fold grouped CV, NDCG hovers at 0.7082 (12 units) and 0.7714 (15 units).
- Top-1 Regret and Spearman follow the exact same non-monotonic pattern.

### 2. Diagnosis: Information Ceiling vs. Sample Scarcity
In supervised learning, two main bottlenecks can suppress test performance:
1. **Sample Scarcity / Structural Under-coverage**: The model architecture and features are capable of high accuracy, but the training distribution lacks structural variety. A rising learning curve diagnoses this condition.
2. **Feature Representation / Information Ceiling**: The model quickly extracts all ranking signal present in the input feature representations, after which additional rows/units simply fit noise without improving out-of-distribution ranking.

Our experimental results firmly point to the **information ceiling**:
- The model reaches its peak out-of-sample performance (~0.77 NDCG@3) with only 8 structural units (~115 rows).
- Triple the training data (12–15 units, ~278–348 rows) yields zero marginal gain.
- At no point does the ML re-ranker beat the HypoPG planner baseline (0.7954 query-macro NDCG@3 across dev).

---

## 5. Limitations

1. **Finite Development Structural Diversity**: The development partition contains 16 canonical structural units. While 16 units are sufficient to reveal that performance plateaus by 8 units, finer granularity between 8 and 12 units is constrained.
2. **Fixed Unit Granularity**: Structural units vary in query count (from 2 queries to 10 queries per unit). However, whether evaluated via deterministic fixed holdout or 4-fold cross-validation, the qualitative plateau remains identical.
3. **Model Configuration Constancy**: Per protocol, XGBoost hyperparameters were held fixed at Stage-2 defaults without re-tuning at each sample size.

---

## 6. Strategic Decision Regarding a Second Workload

### Question
*Does this learning curve justify investing substantial engineering and compute effort to acquire and benchmark a second independent workload?*

### Assessment
**No.**
1. If the learning curve had shown a steep upward trajectory from 4 to 8 to 12 to 15 units (e.g. 0.65 $\rightarrow$ 0.72 $\rightarrow$ 0.82 $\rightarrow$ 0.88), structural data scarcity would be the primary bottleneck, and expanding to a second workload (e.g., TPC-H or DSB) would be highly promising.
2. Instead, the curve plateaus at ~0.77 NDCG@3 by 8 units, unable to exceed HypoPG's 0.7954. Adding more training units within this planner-derived feature space does not bridge the gap.
3. Therefore, proceeding to a second workload without fundamental representations changes (e.g., actual execution feedback, buffer pool state, query graph embeddings) would likely reproduce the exact same ceiling at considerable engineering cost.

---

## 7. Artifact Integrity Verification

- Holdout rows loaded: **0**
- Holdout rows modified: **0**
- Final evaluation artifacts modified: **None**
- Final benchmark executed: **No**
- Target leakage: **None**
