import json
from unittest.mock import MagicMock, patch
from src.dataset.real_benchmark_executor import (
    DEFAULT_REPETITIONS,
    DEFAULT_WARMUPS,
    _run_explain_analyze,
    benchmark_query,
    extract_execution_time,
    extract_planning_time,
    parse_explain_json,
)
from src.dataset.real_index_benchmark import (
    DEFAULT_REPETITIONS as REAL_IDX_DEFAULT_REPETITIONS,
    DEFAULT_WARMUPS as REAL_IDX_DEFAULT_WARMUPS,
)


def test_parse_explain_json_valid_formats():
    """Verify that parse_explain_json handles dict, list of dicts, and JSON strings."""
    sample_data = {
        "Plan": {"Node Type": "Seq Scan", "Relation Name": "title"},
        "Planning Time": 0.45,
        "Execution Time": 12.34,
    }

    # Dict directly
    res1 = parse_explain_json(sample_data)
    assert res1 == sample_data

    # List with one dict
    res2 = parse_explain_json([sample_data])
    assert res2 == sample_data

    # JSON string of list
    res3 = parse_explain_json(json.dumps([sample_data]))
    assert res3 == sample_data

    # JSON string of dict
    res4 = parse_explain_json(json.dumps(sample_data))
    assert res4 == sample_data


def test_parse_explain_json_malformed_and_missing():
    """Verify explicit error handling for missing/malformed/empty inputs."""
    # None input
    try:
        parse_explain_json(None)
        assert False, "Expected ValueError for None"
    except ValueError as e:
        assert "EXPLAIN result is None" in str(e)

    # Empty string
    try:
        parse_explain_json("   ")
        assert False, "Expected ValueError for empty string"
    except ValueError as e:
        assert "empty string" in str(e)

    # Malformed JSON string
    try:
        parse_explain_json("{ malformed json }")
        assert False, "Expected ValueError for malformed JSON"
    except ValueError as e:
        assert "Malformed EXPLAIN JSON string" in str(e)

    # Empty list
    try:
        parse_explain_json([])
        assert False, "Expected ValueError for empty list"
    except ValueError as e:
        assert "empty list" in str(e)

    # Non-dict in list
    try:
        parse_explain_json(["not_a_dict"])
        assert False, "Expected ValueError for non-dict element"
    except ValueError as e:
        assert "Expected dict from EXPLAIN JSON" in str(e)

    # Non-dict primitive
    try:
        parse_explain_json(12345)
        assert False, "Expected ValueError for primitive type"
    except ValueError as e:
        assert "Expected dict from EXPLAIN JSON" in str(e)


def test_extract_execution_time_valid():
    """Verify that extract_execution_time extracts Execution Time correctly."""
    # Float value
    assert extract_execution_time({"Execution Time": 12.34}) == 12.34

    # Integer value
    assert extract_execution_time({"Execution Time": 50}) == 50.0

    # Numeric string
    assert extract_execution_time({"Execution Time": "33.7"}) == 33.7

    # Inside list wrapper
    assert extract_execution_time([{"Execution Time": 8.5}]) == 8.5

    # Inside JSON string
    assert extract_execution_time(json.dumps([{"Execution Time": 99.1}])) == 99.1


def test_extract_execution_time_malformed_and_missing():
    """Verify explicit error handling for missing/malformed Execution Time."""
    # Missing field
    try:
        extract_execution_time({"Planning Time": 1.0})
        assert False, "Expected ValueError for missing Execution Time"
    except ValueError as e:
        assert "did not return 'Execution Time'" in str(e)

    # None field
    try:
        extract_execution_time({"Execution Time": None})
        assert False, "Expected ValueError for None Execution Time"
    except ValueError as e:
        assert "'Execution Time' field is None" in str(e)

    # Non-numeric string
    try:
        extract_execution_time({"Execution Time": "invalid_number"})
        assert False, "Expected ValueError for non-numeric Execution Time"
    except ValueError as e:
        assert "Malformed 'Execution Time' value" in str(e)

    # Negative value
    try:
        extract_execution_time({"Execution Time": -10.5})
        assert False, "Expected ValueError for negative Execution Time"
    except ValueError as e:
        assert "negative 'Execution Time'" in str(e)


def test_extract_planning_time_valid():
    """Verify that extract_planning_time extracts Planning Time correctly."""
    # Float value
    assert extract_planning_time({"Planning Time": 0.52}) == 0.52

    # Integer value
    assert extract_planning_time({"Planning Time": 4}) == 4.0

    # Numeric string
    assert extract_planning_time({"Planning Time": "2.8"}) == 2.8

    # Inside list wrapper
    assert extract_planning_time([{"Planning Time": 1.15}]) == 1.15

    # Inside JSON string
    assert extract_planning_time(json.dumps([{"Planning Time": 3.75}])) == 3.75


def test_extract_planning_time_malformed_and_missing():
    """Verify explicit error handling for missing/malformed Planning Time."""
    # Missing field
    try:
        extract_planning_time({"Execution Time": 10.0})
        assert False, "Expected ValueError for missing Planning Time"
    except ValueError as e:
        assert "did not return 'Planning Time'" in str(e)

    # None field
    try:
        extract_planning_time({"Planning Time": None})
        assert False, "Expected ValueError for None Planning Time"
    except ValueError as e:
        assert "'Planning Time' field is None" in str(e)

    # Non-numeric string
    try:
        extract_planning_time({"Planning Time": "not_a_float"})
        assert False, "Expected ValueError for non-numeric Planning Time"
    except ValueError as e:
        assert "Malformed 'Planning Time' value" in str(e)

    # Negative value
    try:
        extract_planning_time({"Planning Time": -0.1})
        assert False, "Expected ValueError for negative Planning Time"
    except ValueError as e:
        assert "negative 'Planning Time'" in str(e)


def test_planning_time_stored_separately_not_in_primary_runtime():
    """
    Verify locked decision:
    - Primary runtime label is strictly 'Execution Time'
    - 'Planning Time' is extracted and stored separately
    - 'Planning Time' must NOT be added into the primary runtime label
    """
    sample_plan = {
        "Execution Time": 100.0,
        "Planning Time": 10.0,
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "test_table",
        },
    }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", return_value=sample_plan):
        result = benchmark_query(
            query="SELECT 1;",
            repetitions=3,
            warmups=0,
            dbname="job_imdb",
        )

    assert result["status"] == "SUCCESS"

    # Authoritative primary runtime label checks:
    # Must be 100.0 (Execution Time), strictly NOT 110.0 (Execution + Planning)
    assert result["runtimes_ms"] == [100.0, 100.0, 100.0]
    assert result["median_runtime_ms"] == 100.0
    assert result["mean_runtime_ms"] == 100.0
    assert result["min_runtime_ms"] == 100.0
    assert result["max_runtime_ms"] == 100.0

    # Separate planning time checks:
    assert result["planning_times_ms"] == [10.0, 10.0, 10.0]
    assert result["planning_time_ms"] == 10.0
    assert result["median_planning_time_ms"] == 10.0
    assert result["mean_planning_time_ms"] == 10.0
    assert result["min_planning_time_ms"] == 10.0
    assert result["max_planning_time_ms"] == 10.0

    # Strict isolation assertion:
    assert result["median_runtime_ms"] != result["median_runtime_ms"] + result["median_planning_time_ms"]
    assert result["median_runtime_ms"] == 100.0


def test_timing_off_and_format_json_present():
    """
    Verify locked decision:
    - EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) is used
    - TIMING OFF is present
    - TIMING ON is absent
    - FORMAT JSON is present
    """
    executed_sql = []
    mock_cur = MagicMock()

    def capture_execute(sql, *args, **kwargs):
        executed_sql.append(sql)

    mock_cur.execute.side_effect = capture_execute
    mock_cur.fetchone.return_value = [
        [
            {
                "Plan": {"Node Type": "Seq Scan"},
                "Planning Time": 1.0,
                "Execution Time": 5.0,
            }
        ]
    ]

    _run_explain_analyze(mock_cur, "SELECT 1;", timeout_ms=5000)

    # Find the EXPLAIN statement among executed queries
    explain_stmts = [s for s in executed_sql if "EXPLAIN" in s]
    assert len(explain_stmts) == 1, f"Expected 1 EXPLAIN statement, got {len(explain_stmts)}"

    stmt = explain_stmts[0].upper()
    assert "ANALYZE" in stmt, "ANALYZE missing from EXPLAIN"
    assert "TIMING OFF" in stmt, "TIMING OFF missing from EXPLAIN"
    assert "TIMING ON" not in stmt, "TIMING ON unexpectedly present in EXPLAIN"
    assert "FORMAT JSON" in stmt, "FORMAT JSON missing from EXPLAIN"


def test_external_wall_clock_not_primary_label():
    """
    Verify locked decision 4:
    External wall-clock is not used as the primary runtime label.
    The primary runtime label is strictly PostgreSQL Execution Time.
    """
    fake_plan = {
        "Execution Time": 12.5,
        "Planning Time": 0.8,
        "Plan": {"Node Type": "Result"},
    }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", return_value=fake_plan):
        res = benchmark_query("SELECT 1;", repetitions=1, warmups=0)

    # Primary label is Execution Time from JSON
    assert res["median_runtime_ms"] == 12.5
    assert res["runtimes_ms"] == [12.5]


def test_complete_json_plan_preserved():
    """
    Verify locked decision 6:
    Preserve complete JSON execution plan/result because we will later need plan features.
    """
    complete_plan_payload = {
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Startup Cost": 10.0,
            "Total Cost": 500.0,
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "t1"},
                {"Node Type": "Seq Scan", "Relation Name": "t2"},
            ],
        },
        "Planning": {
            "Shared Hit Blocks": 12,
        },
        "Planning Time": 1.23,
        "Triggers": [],
        "Execution Time": 45.67,
    }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", return_value=complete_plan_payload):
        res = benchmark_query("SELECT 1;", repetitions=1, warmups=0)

    stored_plan = res["plan"]
    assert stored_plan is not None
    assert "Plan" in stored_plan
    assert stored_plan["Plan"]["Node Type"] == "Hash Join"
    assert len(stored_plan["Plan"]["Plans"]) == 2
    assert "Planning" in stored_plan
    assert stored_plan["Planning"]["Shared Hit Blocks"] == 12
    assert stored_plan["Execution Time"] == 45.67
    assert stored_plan["Planning Time"] == 1.23


def test_default_warmup_and_repetition_constants():
    """Verify locked protocol constants: exactly 2 warmups and 5 measured repetitions."""
    assert DEFAULT_WARMUPS == 2, f"Expected DEFAULT_WARMUPS == 2, got {DEFAULT_WARMUPS}"
    assert DEFAULT_REPETITIONS == 5, f"Expected DEFAULT_REPETITIONS == 5, got {DEFAULT_REPETITIONS}"
    assert REAL_IDX_DEFAULT_WARMUPS == 2
    assert REAL_IDX_DEFAULT_REPETITIONS == 5


def test_exactly_two_warmups_occur_before_five_measured_executions():
    """
    Verify that:
    1. Exactly 2 warmups occur first.
    2. Exactly 5 measured executions occur next.
    3. Total executions = 7.
    """
    call_records = []

    def mock_explain_analyze(cur, query, timeout_ms):
        call_idx = len(call_records) + 1
        call_records.append(call_idx)
        return {
            "Plan": {"Node Type": "Seq Scan", "Relation Name": "test"},
            "Planning Time": 0.5,
            "Execution Time": float(call_idx * 10),
        }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        result = benchmark_query(
            query="SELECT 1;",
            dbname="job_imdb",
        )

    assert result["status"] == "SUCCESS"
    assert result["warmups"] == 2
    assert result["repetitions"] == 5

    # Total executions must be 2 + 5 = 7
    assert len(call_records) == 7, f"Expected 7 total executions, got {len(call_records)}"

    # First 2 were warmups (call 1: 10.0ms, call 2: 20.0ms)
    # Next 5 were measured runs (call 3: 30.0ms, call 4: 40.0ms, call 5: 50.0ms, call 6: 60.0ms, call 7: 70.0ms)
    assert result["runtimes_ms"] == [30.0, 40.0, 50.0, 60.0, 70.0]


def test_warmups_excluded_from_runtime_statistics():
    """
    Verify that warmup runtimes do NOT contribute to:
    - runtimes_ms
    - median_runtime_ms
    - mean_runtime_ms
    - min_runtime_ms
    - max_runtime_ms
    - planning_times_ms
    """
    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            # Extreme warmup values that would distort stats if leaked
            return {
                "Plan": {"Node Type": "Seq Scan"},
                "Planning Time": 9999.0,
                "Execution Time": 999999.0,
            }
        # Realistic measured values
        return {
            "Plan": {"Node Type": "Seq Scan"},
            "Planning Time": 1.0,
            "Execution Time": 10.0 + call_count,
        }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        result = benchmark_query("SELECT 1;", dbname="job_imdb")

    assert result["status"] == "SUCCESS"
    assert len(result["runtimes_ms"]) == 5

    # Ensure warmup values are completely absent from all statistics
    assert 999999.0 not in result["runtimes_ms"]
    assert result["median_runtime_ms"] < 100.0
    assert result["mean_runtime_ms"] < 100.0
    assert result["min_runtime_ms"] < 100.0
    assert result["max_runtime_ms"] < 100.0

    # Warmup planning time must also be excluded
    assert 9999.0 not in result["planning_times_ms"]


def test_all_five_measured_runtimes_preserved():
    """Verify that all five measured runtimes are preserved in order for variance analysis."""
    measured_times = [12.4, 15.8, 11.2, 14.1, 13.5]
    measured_plans = [
        {
            "Plan": {"Node Type": "Seq Scan"},
            "Planning Time": 0.8,
            "Execution Time": t,
        }
        for t in measured_times
    ]

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return {"Plan": {}, "Planning Time": 0.5, "Execution Time": 100.0}
        return measured_plans[call_count - 3]

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        result = benchmark_query("SELECT 1;", dbname="job_imdb")

    assert result["status"] == "SUCCESS"
    assert result["runtimes_ms"] == measured_times
    assert len(result["runtimes_ms"]) == 5


def test_median_calculated_correctly_and_differs_from_mean():
    """
    Verify that the primary statistic is the MEDIAN of the 5 runs,
    specifically testing asymmetric data where median != mean.
    """
    # Raw measured runtimes: [10.0, 11.0, 12.0, 13.0, 104.0]
    # Sorted: [10.0, 11.0, 12.0, 13.0, 104.0]
    # Median = 12.0
    # Mean = 30.0
    asymmetric_times = [10.0, 11.0, 12.0, 13.0, 104.0]
    measured_plans = [
        {"Plan": {}, "Planning Time": 1.0, "Execution Time": t}
        for t in asymmetric_times
    ]

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return {"Plan": {}, "Planning Time": 0.5, "Execution Time": 50.0}
        return measured_plans[call_count - 3]

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        result = benchmark_query("SELECT 1;", dbname="job_imdb")

    assert result["status"] == "SUCCESS"
    assert result["median_runtime_ms"] == 12.0, f"Expected median 12.0, got {result['median_runtime_ms']}"
    assert result["mean_runtime_ms"] == 30.0
    assert result["median_runtime_ms"] != result["mean_runtime_ms"], "Median must not equal mean in asymmetric sample"


def test_planning_time_remains_separate_under_repetition_protocol():
    """Verify that all 5 Planning Times are collected and stored separately from Execution Time."""
    measured_planning = [1.1, 1.3, 0.9, 1.5, 1.2]
    measured_execution = [20.0, 22.0, 21.0, 23.0, 20.5]

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return {"Plan": {}, "Planning Time": 0.5, "Execution Time": 50.0}
        idx = call_count - 3
        return {
            "Plan": {},
            "Planning Time": measured_planning[idx],
            "Execution Time": measured_execution[idx],
        }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        result = benchmark_query("SELECT 1;", dbname="job_imdb")

    assert result["status"] == "SUCCESS"
    assert result["planning_times_ms"] == measured_planning
    assert len(result["planning_times_ms"]) == 5
    assert result["median_planning_time_ms"] == 1.2
    assert result["median_runtime_ms"] == 21.0

    # Strict isolation: primary runtime does not include planning time
    assert result["median_runtime_ms"] not in [21.0 + 1.2, 22.2]


def main():
    print("=" * 70)
    print("RUNNING RUNTIME MEASUREMENT & REPETITION PROTOCOL TESTS")
    print("=" * 70)

    test_parse_explain_json_valid_formats()
    print("test_parse_explain_json_valid_formats: PASSED")

    test_parse_explain_json_malformed_and_missing()
    print("test_parse_explain_json_malformed_and_missing: PASSED")

    test_extract_execution_time_valid()
    print("test_extract_execution_time_valid: PASSED")

    test_extract_execution_time_malformed_and_missing()
    print("test_extract_execution_time_malformed_and_missing: PASSED")

    test_extract_planning_time_valid()
    print("test_extract_planning_time_valid: PASSED")

    test_extract_planning_time_malformed_and_missing()
    print("test_extract_planning_time_malformed_and_missing: PASSED")

    test_planning_time_stored_separately_not_in_primary_runtime()
    print("test_planning_time_stored_separately_not_in_primary_runtime: PASSED")

    test_timing_off_and_format_json_present()
    print("test_timing_off_and_format_json_present: PASSED")

    test_external_wall_clock_not_primary_label()
    print("test_external_wall_clock_not_primary_label: PASSED")

    test_complete_json_plan_preserved()
    print("test_complete_json_plan_preserved: PASSED")

    # Decision #4: Warm-cache and Repetition Protocol tests
    test_default_warmup_and_repetition_constants()
    print("test_default_warmup_and_repetition_constants: PASSED")

    test_exactly_two_warmups_occur_before_five_measured_executions()
    print("test_exactly_two_warmups_occur_before_five_measured_executions: PASSED")

    test_warmups_excluded_from_runtime_statistics()
    print("test_warmups_excluded_from_runtime_statistics: PASSED")

    test_all_five_measured_runtimes_preserved()
    print("test_all_five_measured_runtimes_preserved: PASSED")

    test_median_calculated_correctly_and_differs_from_mean()
    print("test_median_calculated_correctly_and_differs_from_mean: PASSED")

    test_planning_time_remains_separate_under_repetition_protocol()
    print("test_planning_time_remains_separate_under_repetition_protocol: PASSED")

    print("=" * 70)
    print("ALL RUNTIME MEASUREMENT & REPETITION TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
