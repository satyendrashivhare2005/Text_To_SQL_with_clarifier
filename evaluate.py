import json
import time
import uuid
from typing import Any, Dict, List, Optional
from langgraph.types import Command
from langgraph_pipeline import app

# ==============================================================================
# BENCHMARK TEST DATASETS: SPIDER (Clean) & AMBROSIA (Ambiguous)
# ==============================================================================

# Suite 1: Spider-Style Benchmark (Unambiguous queries testing fast-path & SQL correctness)
SPIDER_BENCHMARK = [
    {
        "id": "SPIDER-01",
        "question": "Show all customers in the Starter tier",
        "description": "Clean filter on customers table with exact enum value",
        "expected_fast_path": True,
        "expected_sql_keywords": ["SELECT", "customers", "Starter"],
    },
    {
        "id": "SPIDER-02",
        "question": "How many completed orders were placed in the last 30 days?",
        "description": "Multi-condition query with explicit date window and status filter",
        "expected_fast_path": True,
        "expected_sql_keywords": ["COUNT", "completed", "DATE_SUB"],
    },
    {
        "id": "SPIDER-03",
        "question": "List company names of non-deleted customers",
        "description": "Clean projection with explicit soft-deletion filter",
        "expected_fast_path": True,
        "expected_sql_keywords": ["SELECT", "company_name", "customers"],
    },
]

# Suite 2: AmBRoSIA-Style Benchmark (Ambiguous queries testing detection & HITL resume)
AMBROSIA_BENCHMARK = [
    {
        "id": "AMBROSIA-01",
        "question": "What was our total revenue in the last 30 days?",
        "description": "COLUMN_COLLISION on metric 'revenue' (Net vs Gross vs Cash)",
        "expected_ambiguity_trigger": "revenue",
        "simulated_user_choice": {"revenue": "net_revenue"},
        "expected_sql_keywords": ["discount_amount", "DATE_SUB"],
    },
    {
        "id": "AMBROSIA-02",
        "question": "Show all orders",
        "description": "MISSING_FILTER on large transaction table 'orders'",
        "expected_ambiguity_trigger": "orders",
        "simulated_user_choice": {"orders": "last_30_days"},
        "expected_sql_keywords": ["DATE_SUB", "orders"],
    },
    {
        "id": "AMBROSIA-03",
        "question": "Show all active customers",
        "description": "UNDEFINED_METRIC on colloquial adjective 'active'",
        "expected_ambiguity_trigger": "active",
        "simulated_user_choice": {"active": "account_flag"},
        "expected_sql_keywords": ["is_active", "customers"],
    },
]


# ==============================================================================
# EVALUATION HARNESS RUNNER
# ==============================================================================
def run_evaluation_suite():
    print("=" * 80)
    print("🚀 RUNNING TEXT-TO-SQL EVALUATION: SPIDER & AMBROSIA BENCHMARKS")
    print("=" * 80)

    results = []

    # --------------------------------------------------------------------------
    # PART 1: EVALUATE SPIDER SUITE (Clean Queries)
    # --------------------------------------------------------------------------
    print("\n[PART 1: SPIDER BENCHMARK - CLEAN UNAMBIGUOUS QUERIES]")
    print("-" * 80)

    for case in SPIDER_BENCHMARK:
        test_id = case["id"]
        question = case["question"]
        thread_id = f"eval_spider_{uuid.uuid4().hex[:6]}"
        config = {"configurable": {"thread_id": thread_id}}

        t0 = time.perf_counter()
        app.invoke({"user_question": question}, config=config)
        latency = (time.perf_counter() - t0) * 1000

        state = app.get_state(config)
        is_interrupted = bool(state.tasks and any(t.interrupts for t in state.tasks))
        fast_path_success = not is_interrupted

        sql = state.values.get("raw_sql", "")
        sql_valid = bool(sql and all(kw.lower() in sql.lower() for kw in case["expected_sql_keywords"]))
        exec_error = state.values.get("sql_error")
        execution_success = (exec_error is None)

        status_str = "✅ PASSED" if (fast_path_success and sql_valid and execution_success) else "❌ FAILED"
        print(f"[{test_id}] '{question}' -> {status_str} ({latency:.1f}ms)")
        if sql:
            print(f"    SQL: {sql[:100]}...")

        results.append({
            "suite": "Spider",
            "id": test_id,
            "fast_path": fast_path_success,
            "clarification_detected": is_interrupted,
            "sql_generated": bool(sql),
            "sql_valid": sql_valid,
            "exec_success": execution_success,
            "latency_ms": latency,
        })

    # --------------------------------------------------------------------------
    # PART 2: EVALUATE AMBROSIA SUITE (Ambiguous Queries with Clarification Resume)
    # --------------------------------------------------------------------------
    print("\n[PART 2: AMBROSIA BENCHMARK - AMBIGUITY DETECTION & HITL RESUME]")
    print("-" * 80)

    for case in AMBROSIA_BENCHMARK:
        test_id = case["id"]
        question = case["question"]
        trigger_term = case["expected_ambiguity_trigger"]
        choices = case["simulated_user_choice"]
        thread_id = f"eval_ambrosia_{uuid.uuid4().hex[:6]}"
        config = {"configurable": {"thread_id": thread_id}}

        # Step 1: Initial invocation (Should pause)
        t0 = time.perf_counter()
        app.invoke({"user_question": question}, config=config)
        step1_latency = (time.perf_counter() - t0) * 1000

        state1 = app.get_state(config)
        is_interrupted = bool(state1.tasks and any(t.interrupts for t in state1.tasks))

        detected_term_match = False
        if is_interrupted:
            payload = state1.tasks[0].interrupts[0].value
            items = payload.get("clarifications", [])
            flagged_terms = [i.get("trigger_term", "").lower() for i in items]
            detected_term_match = any(trigger_term.lower() in t for t in flagged_terms)

        # Step 2: Resume execution with simulated user choices
        t1 = time.perf_counter()
        app.invoke(Command(resume=choices), config=config)
        step2_latency = (time.perf_counter() - t1) * 1000
        total_latency = step1_latency + step2_latency

        state2 = app.get_state(config)
        sql = state2.values.get("raw_sql", "")
        sql_valid = bool(sql and all(kw.lower() in sql.lower() for kw in case["expected_sql_keywords"]))
        exec_error = state2.values.get("sql_error")
        execution_success = (exec_error is None)

        status_str = "✅ PASSED" if (is_interrupted and detected_term_match and sql_valid and execution_success) else "❌ FAILED"
        print(f"[{test_id}] '{question}' -> {status_str} (Ambiguity Paused: {is_interrupted}, Total: {total_latency:.1f}ms)")
        if sql:
            print(f"    Resumed SQL: {sql[:100]}...")

        results.append({
            "suite": "AmBRoSIA",
            "id": test_id,
            "fast_path": not is_interrupted,
            "clarification_detected": is_interrupted,
            "sql_generated": bool(sql),
            "sql_valid": sql_valid,
            "exec_success": execution_success,
            "latency_ms": total_latency,
        })

    # --------------------------------------------------------------------------
    # PART 3: CALCULATE AND DISPLAY BENCHMARK METRICS
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("📊 BENCHMARK EVALUATION SCORECARD")
    print("=" * 80)

    spider_runs = [r for r in results if r["suite"] == "Spider"]
    ambrosia_runs = [r for r in results if r["suite"] == "AmBRoSIA"]

    spider_fast_path = (sum(1 for r in spider_runs if r["fast_path"]) / len(spider_runs)) * 100
    spider_exec_acc = (sum(1 for r in spider_runs if r["exec_success"] and r["sql_valid"]) / len(spider_runs)) * 100

    ambrosia_recall = (sum(1 for r in ambrosia_runs if r["clarification_detected"]) / len(ambrosia_runs)) * 100
    ambrosia_post_acc = (sum(1 for r in ambrosia_runs if r["exec_success"] and r["sql_valid"]) / len(ambrosia_runs)) * 100

    overall_exec_acc = (sum(1 for r in results if r["exec_success"] and r["sql_valid"]) / len(results)) * 100
    avg_latency = sum(r["latency_ms"] for r in results) / len(results)

    print(f"| Metric Name                               | Score      | Industry Target |")
    print(f"|-------------------------------------------|------------|-----------------|")
    print(f"| Spider Fast-Path Rate (No False Alarms)   | {spider_fast_path:>6.1f}%   | > 90.0%         |")
    print(f"| Spider Clean Execution Accuracy (EX)      | {spider_exec_acc:>6.1f}%   | > 85.0%         |")
    print(f"| AmBRoSIA Ambiguity Detection Recall       | {ambrosia_recall:>6.1f}%   | 100.0%          |")
    print(f"| AmBRoSIA Post-Clarification Accuracy (PCA)| {ambrosia_post_acc:>6.1f}%   | > 90.0%         |")
    print(f"| Overall Pipeline Execution Success        | {overall_exec_acc:>6.1f}%   | > 90.0%         |")
    print(f"| Average Pipeline Latency                  | {avg_latency:>6.0f} ms  | < 5000 ms       |")
    print("=" * 80)
    print("🎯 Verification complete: All benchmark suites executed successfully!\n")


if __name__ == "__main__":
    run_evaluation_suite()
