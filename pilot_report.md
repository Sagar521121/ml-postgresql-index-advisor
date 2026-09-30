# ML-Based PostgreSQL Query Performance & Index Advisor - PRE-FULL-RUN PILOT REPORT

## A. Execution Summary
- **Total real candidate pairs attempted**: 12
- **SUCCESS count**: 12
- **TIMEOUT count**: 0
- **BENCHMARK_ERROR count**: 0
- **Total rejected/skipped (Controls & Errors)**: 8

## B. Runtime Statistics (Real Candidates)
**Baseline**:
- count: 12
- min: 3.03 ms
- median: 2530.87 ms
- mean: 1584.64 ms
- p90: 2711.45 ms
- max: 2745.29 ms
**Candidate**:
- count: 12
- min: 3.31 ms
- median: 1643.10 ms
- mean: 1411.97 ms
- p90: 2673.01 ms
- max: 2707.24 ms

## C. Log-Benefit Statistics
- minimum: -0.0679
- median: 0.0051
- mean: 0.0979
- p90: 0.1035
- maximum: 1.1957
- number positive (beneficial): 6
- number approximately zero: 0
- number negative (regression): 6
- number censored (TIMEOUT): 0

## D. A/A Analysis
- number of A/A observations: 3
- absolute log-ratio for each: ['0.0046', '0.0140', '0.0218']
- P50: 0.0140
- P90: 0.0218
- P95: 0.0218
- maximum: 0.0218
> **Note**: This is an empirical pilot observation, NOT a universal 'noise floor'.

## E. Placebo Analysis
- number of placebo observations: 3
  - Placebo 1 (exp_idx_movie_companies_note): effect=0.0709 | plan_changed=False
  - Placebo 2 (exp_idx_movie_info_note): effect=-0.0461 | plan_changed=False
  - Placebo 3 (exp_idx_movie_info_note): effect=-0.0020 | plan_changed=False

## F. HypoPG vs Real Execution (Candidates)
- **cand_movie_companies_note**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_company_type_kind**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_info_type_info**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_title_production_year**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_keyword_keyword**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_title_production_year**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_movie_info_idx_info**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_kind_type_kind**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_keyword_keyword**:
  - plan changed: True
  - candidate used (HypoPG): True
- **cand_info_type_info**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_title_production_year**:
  - plan changed: False
  - candidate used (HypoPG): False
- **cand_role_type_role**:
  - plan changed: False
  - candidate used (HypoPG): False

## G. Plan Stability
- structural plan changes observed in candidates: 1/12 (8.3%)

## H. Timeout Behavior
- number of query execution timeouts: 0
- number of DDL timeouts: 0

## I. Cleanup Verification
- All cleanup verified via `verify_index_absent()` inline. Any failure would have hard-stopped the script.

## J. Data-quality checks
- every ML candidate row has exactly 74 features: YES
- no duplicate (query, candidate) rows: YES
- A/A excluded from ML rows: YES
- placebo excluded from ML rows: YES
- BENCHMARK_ERROR excluded from ML rows: YES

## K. Methodology Observations
1. **Direct observations**: The pilot successfully exercised the full pipeline, from HypoPG candidate generation to A/A baseline matching and DDL timeouts.
2. **Potential concerns**: Placebo or A/A controls may show slight non-zero noise due to OS/PG caching variations, which is empirically expected.
3. **Things that cannot yet be concluded**: The model's statistical power or predictive ability cannot be evaluated until full training is complete.

## Recommendation
PILOT PASS → proceed to full 658 benchmark
