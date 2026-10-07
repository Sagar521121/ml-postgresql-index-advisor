# Controlled Model Comparison Experiment Report

## Executive Summary

This experiment evaluates whether alternative configurations or simpler inductive biases outperform the current Stage-2 XGBoost model on the **371-row development dataset**. 
We employed a rigorous **16-fold Leave-One-Structural-Unit-Out Cross-Validation (LOUOCV)** scheme across all 16 development structural units.
**The frozen 228-row holdout dataset was NOT used, loaded, or evaluated.**

### Pre-Specified Decision Rule Result
- **Rule**: Challenger must achieve $\ge +0.02$ Mean Macro NDCG@3 improvement vs. Stage-2 Reference AND improve on $\ge 10/16$ structural units.
- **Outcome**: **No ML challenger satisfied the criteria.**
- **Formal Conclusion**: **Stage-2 XGBoost remains the development-set reference.**

---

## 1. Dataset & Cross-Validation Protocol

- **Development Set**: Exactly 371 rows across 78 queries and 16 canonical structural units from JOB/IMDb.
- **Holdout Isolation**: 228 rows (4 unseen structural units) remained strictly isolated and untouched.
- **Cross-Validation Scheme**: 16-fold Leave-One-Structural-Unit-Out. In each fold $k$:
  - Training: 15 structural units (~348–369 rows).
  - Validation: 1 held-out structural unit (2–79 rows).
  - Preprocessing (e.g. `StandardScaler` for Ridge, query de-meaning) fitted strictly inside each training fold. Zero validation leakage.

---

## 2. Feature Sets Tested

- **Feature Set A (74 features)**: The full explicit whitelist of planner-derived features used in Stage 1 and Stage 2.
- **Feature Set B (49 features)**: Unsupervised ablation removing the 25 features that have zero variance ($\text{std} = 0.0$) across the development set.
  - *Removed 25 constant features*: `baseline_plan_rows`, `hypo_plan_rows`, `plan_rows_delta`, `plan_width_delta`, all `tid_scan_*`, `merge_join_*`, `sort_*`, `incremental_sort_*`, `aggregate_*`, `gather_*`, and `gather_merge_*` counts and deltas.

---

## 3. Models Evaluated

1. **Stage-2 XGBoost Reference**: `max_depth=2, min_child_weight=2, lr=0.1, n_est=200, colsample=0.6, reg_lambda=1.0, random_state=42`.
2. **Stage-1 XGBoost Baseline**: `max_depth=3, lr=0.1, n_est=100, random_state=42`.
3. **Ridge Regression**: Tested at $\alpha \in \{1.0, 10.0, 100.0\}$ with fold-isolated standard scaling.
4. **XGBoost Query-Demeaned Target**: Stage-2 architecture trained on $y - \bar{y}_{q,\text{train}}$. At inference time, validation candidate ranking is conducted on predicted within-query deviation $\hat{y}_{\text{demeaned}}$ DESC without accessing validation query ground truth.
5. **HypoPG Planner Baseline**: `hypo_total_cost ASC, candidate_id ASC`.
6. **Random Baseline**: Query-seeded RNG `random.Random(f"{query_id}_42")`.

---

## 4. Aggregate Results Across 16 Structural Units

| Model | Feat | Unit NDCG@3 (±std) | Query NDCG@3 | Top-1 Regret | Spearman | RMSE | $\Delta$ vs Ref | Units Impr (out of 16) |
|---|---|---|---|---|---|---|---|---|
| **XGBoost Stage-2 Reference** | 74 | 0.7543 ± 0.1468 | 0.7621 | 0.1447 | 0.1109 | 0.4163 | **REFERENCE** | — |
| **XGBoost Stage-2** | 49 | 0.7719 ± 0.1367 | 0.7714 | 0.1291 | 0.1267 | 0.4011 | +0.0176 | 2 / 16 (12 tied) |
| **XGBoost Stage-1 Baseline** | 74 | 0.7690 ± 0.1519 | 0.7689 | 0.1425 | 0.1155 | 0.4447 | +0.0147 | 3 / 16 (11 tied) |
| **XGBoost Stage-1 Baseline** | 49 | 0.7690 ± 0.1519 | 0.7689 | 0.1425 | 0.1155 | 0.4447 | +0.0147 | 3 / 16 (11 tied) |
| **Ridge ($\alpha=100.0$)** | 74 | 0.7410 ± 0.1848 | 0.7444 | 0.1420 | 0.0604 | 0.4806 | -0.0133 | 4 / 16 (5 tied) |
| **Ridge ($\alpha=100.0$)** | 49 | 0.7362 ± 0.1901 | 0.7406 | 0.1440 | 0.0403 | 0.4806 | -0.0181 | 3 / 16 (6 tied) |
| **Ridge ($\alpha=10.0$)** | 74 | 0.6962 ± 0.2318 | 0.6662 | 0.1831 | 0.0570 | 0.5454 | -0.0581 | 3 / 16 (8 tied) |
| **Ridge ($\alpha=10.0$)** | 49 | 0.6785 ± 0.2362 | 0.6519 | 0.1840 | 0.0198 | 0.5454 | -0.0759 | 3 / 16 (6 tied) |
| **Ridge ($\alpha=1.0$)** | 74 | 0.6889 ± 0.2402 | 0.6620 | 0.1858 | 0.0418 | 0.6881 | -0.0654 | 3 / 16 (6 tied) |
| **Ridge ($\alpha=1.0$)** | 49 | 0.6892 ± 0.2443 | 0.6650 | 0.1869 | 0.0285 | 0.6881 | -0.0651 | 3 / 16 (7 tied) |
| **XGBoost Query-Demeaned** | 49 | 0.7314 ± 0.1917 | 0.7185 | 0.1547 | 0.0417 | 0.3826 | -0.0229 | 4 / 16 (7 tied) |
| **XGBoost Query-Demeaned** | 74 | 0.7230 ± 0.1726 | 0.7222 | 0.1561 | 0.0286 | 0.4054 | -0.0313 | 3 / 16 (9 tied) |
| **HypoPG Planner Baseline** | — | **0.8003 ± 0.1383** | **0.7954** | **0.0994** | **0.1921** | N/A | +0.0460 | 5 / 16 (10 tied) |
| **Random Baseline** | — | 0.6600 ± 0.2080 | 0.6201 | 0.5291 | 0.0142 | N/A | -0.0943 | 6 / 16 (1 tied) |

---

## 5. Detailed Breakdown by Structural Unit (NDCG@3)

| Unit | Queries | Rows | XGB S2 (74) | XGB S2 (49) | XGB S1 (74) | Ridge (100) | Demeaned (49) | HypoPG | Random |
|---|---|---|---|---|---|---|---|---|---|
| **C70_3** | 10 | 79 | 0.7624 | 0.7587 | 0.7624 | 0.7105 | 0.7587 | 0.7624 | 0.3686 |
| **C70_4** | 9 | 55 | 0.8114 | 0.8114 | 0.7937 | 0.7284 | 0.3736 | 0.7937 | 0.4557 |
| **C70_5** | 6 | 27 | 0.6570 | 0.6166 | 0.6142 | 0.6142 | 0.5972 | 0.6570 | 0.4831 |
| **C70_6** | 10 | 24 | 0.9255 | 0.9255 | 0.9255 | 0.9255 | 0.9255 | 0.9255 | 0.8335 |
| **C70_7** | 6 | 48 | 0.6879 | 0.6986 | 0.6978 | 0.4755 | 0.6986 | 0.6978 | 0.4059 |
| **Singleton_1** | 4 | 15 | 0.6576 | 0.6576 | 0.6576 | 0.6576 | 0.6576 | 0.6576 | 0.7571 |
| **Singleton_10**| 2 | 7 | 0.8589 | 0.8589 | 0.8589 | 0.3932 | 0.3932 | 0.8589 | 0.8225 |
| **Singleton_14**| 3 | 16 | 0.6929 | 0.6929 | 0.9426 | 0.9426 | 0.9426 | 0.9426 | 0.3894 |
| **Singleton_15**| 4 | 19 | 0.5829 | 0.5829 | 0.6186 | 0.5704 | 0.6186 | 0.6186 | 0.6542 |
| **Singleton_18**| 3 | 13 | 0.5068 | 0.5068 | 0.5068 | 0.5205 | 0.4970 | 0.5068 | 0.8183 |
| **Singleton_2** | 4 | 8 | 0.8155 | 0.8155 | 0.8155 | 0.8155 | 0.8155 | 0.8155 | 0.9077 |
| **Singleton_3** | 3 | 6 | 0.9982 | 0.9982 | 0.9982 | 0.9982 | 0.9982 | 0.9982 | 0.8770 |
| **Singleton_32**| 2 | 2 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| **Singleton_4** | 3 | 12 | 0.5192 | 0.8337 | 0.5192 | 0.8337 | 0.8337 | 0.8337 | 0.5745 |
| **Singleton_6** | 6 | 17 | 0.7732 | 0.7732 | 0.7732 | 0.9174 | 0.7732 | 0.9174 | 0.7913 |
| **Singleton_7** | 3 | 23 | 0.8197 | 0.8197 | 0.8197 | 0.7536 | 0.8197 | 0.8197 | 0.4210 |

---

## 6. Key Scientific Findings

### A. Does Removing Constant Features Help? (74 vs 49 Features)
- **Modest positive trend for Stage-2**: Unit NDCG rises from $0.7543$ to $0.7719$ ($+0.0176$). Regret improves from $0.1447$ to $0.1291$.
- **Consistency**: The improvement is concentrated in `Singleton_4` (jump from $0.5192$ to $0.8337$) and `C70_7` ($0.6879 \rightarrow 0.6986$), with a slight dip in `C70_5` ($0.6570 \rightarrow 0.6166$). On 12 of 16 units, predictions are exactly tied.
- **For Stage-1**: Identical performance ($0.7690$ vs $0.7690$), showing depth=3 was unaffected by constant columns.

### B. Does a Simpler Linear Model Generalize Better? (Ridge vs XGBoost)
- **No.** Ridge underperforms significantly at lower regularization ($\alpha=1.0$: NDCG $0.6889$; $\alpha=10.0$: NDCG $0.6962$).
- Heavily regularized Ridge ($\alpha=100.0$) approaches XGBoost ($0.7410$ vs $0.7543$), but suffers severe collapse on individual units (e.g., `Singleton_10` drops to $0.3932$).
- **Conclusion**: The ranking signal requires nonlinear interaction modeling; tree-based models are fundamentally better aligned than regularized linear regressions.

### C. Does Returning to Stage-1 Configuration Help? (Stage-1 vs Stage-2)
- **Yes, slightly**: Stage-1 (depth=3, 100 trees) achieves $0.7690$ unit NDCG compared to Stage-2's $0.7543$ ($+0.0147$).
- Stage-1 improves on 3 units (`Singleton_14`: $0.6929 \rightarrow 0.9426$, `Singleton_15`: $0.5829 \rightarrow 0.6186$, `C70_7`: $0.6879 \rightarrow 0.6978$) and degrades on 2 (`C70_4`, `C70_5`).
- This reinforces the Audit 7 finding: optimizing exclusively for lowest CV RMSE during Stage 2 slightly sacrificed ranking capacity.

### D. Does Removing Between-Query Target Variation Help? (Query-Demeaned Target)
- **No, it degrades ranking**: Demeaned XGBoost drops to $0.7230$ (74 feat) and $0.7314$ (49 feat).
- While demeaned modeling achieved lower raw RMSE ($0.3826$), it degraded NDCG on `C70_4` ($0.8114 \rightarrow 0.3736$) and `Singleton_10` ($0.8589 \rightarrow 0.3932$).
- **Explanation**: Absolute plan cost differences between queries provide implicit context regarding query scale and sensitivity that is lost when training on demeaned residuals.

### E. How Strong is HypoPG on Development Folds?
- **HypoPG dominates all ML approaches**: Mean Unit NDCG = $0.8003$, Query NDCG = $0.7954$, Regret = $0.0994$, Spearman = $0.1921$.
- HypoPG outperforms the Stage-2 reference by $+0.0460$ on average, winning on 5 units and tying on 10 units. It is beaten by XGBoost on only 1 unit (`C70_4`: $0.8114$ vs $0.7937$).
- This confirms that **HypoPG's superiority is not an artifact of the holdout test set**; HypoPG is systematically stronger across the training structural units as well.

---

## 7. Decision-Rule Conclusion

- **Threshold requirement**: Mean NDCG gain $\ge +0.02$ AND $\ge 10/16$ units improved.
- **Top ML challenger**: Stage-2 XGBoost with 49 features ($+0.0176$ gain, 2 units improved, 12 tied, 2 degraded).
- **Result**: Fails both conditions.
- **Official Verdict**: **Stage-2 XGBoost remains the development-set reference.**
