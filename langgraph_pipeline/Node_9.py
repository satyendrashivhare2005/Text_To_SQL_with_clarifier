import json
import os
from typing import Any, Dict, Optional, Tuple
import sqlglot
from sqlglot import exp

try:
    from sqlalchemy import create_engine, text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

# Default safety thresholds
COST_THRESHOLD = 50000.0
ROW_THRESHOLD = 50000
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


# Helper to get optional MySQL SQLAlchemy engine
def get_mysql_engine():
    if not HAS_SQLALCHEMY:
        return None
    db_url = os.getenv("MYSQL_DATABASE_URL")
    if not db_url:
        return None
    try:
        return create_engine(db_url, pool_pre_ping=True)
    except Exception:
        return None


# Enforce safe LIMIT clause on SELECT query AST
def validate_limit(
    query: str,
    dialect: str = "mysql",
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> Tuple[bool, str, Optional[str]]:
    # Parse SQL into AST
    try:
        parsed = sqlglot.parse_one(query, read=dialect)
    except Exception as e:
        return False, query, f"SQL Syntax Error: {e}"

    # Only SELECT queries are permitted
    if not isinstance(parsed, exp.Select):
        return False, query, "Security Violation: Only SELECT queries are permitted."

    # Auto-inject default LIMIT if missing
    limit_node = parsed.find(exp.Limit)
    if not limit_node:
        parsed = parsed.limit(default_limit)
        return True, parsed.sql(dialect=dialect), None

    # Clamp limit if it exceeds maximum allowable limit
    try:
        limit_val = int(limit_node.expression.this)
        if limit_val > max_limit:
            parsed = parsed.limit(max_limit)
    except (ValueError, TypeError, AttributeError):
        pass

    return True, parsed.sql(dialect=dialect), None


# Recursively extract cost and rows examined from MySQL EXPLAIN JSON
def parse_mysql_explain(plan_dict: dict) -> Tuple[float, int, bool]:
    query_block = plan_dict.get("query_block", {})
    cost_info = query_block.get("cost_info", {})
    try:
        query_cost = float(cost_info.get("query_cost", 0.0))
    except (ValueError, TypeError):
        query_cost = 0.0

    total_rows = 0
    has_full_table_scan = False

    # Recursive traversal to collect all table scan costs
    def scan_nodes(node: Any):
        nonlocal total_rows, has_full_table_scan
        if isinstance(node, dict):
            if "table" in node and isinstance(node["table"], dict):
                tbl = node["table"]
                rows = tbl.get("rows_examined_per_scan", 0)
                try:
                    total_rows += int(rows)
                except (ValueError, TypeError):
                    pass
                if str(tbl.get("access_type", "")).upper() == "ALL":
                    has_full_table_scan = True
            for val in node.values():
                scan_nodes(val)
        elif isinstance(node, list):
            for item in node:
                scan_nodes(item)

    scan_nodes(query_block)
    return query_cost, total_rows, has_full_table_scan


# Run MySQL EXPLAIN FORMAT=JSON dry-run cost check
def validate_and_explain(
    safe_sql: str,
    engine=None,
    max_cost: float = COST_THRESHOLD,
    max_rows: int = ROW_THRESHOLD,
) -> Tuple[bool, str, dict]:
    # Bypass check if MySQL engine is not connected
    if engine is None:
        return True, "Offline mode: MySQL EXPLAIN check bypassed", {}

    # Strip semicolon for EXPLAIN prefix
    clean_sql = safe_sql.strip().rstrip(";")
    explain_query = f"EXPLAIN FORMAT=JSON {clean_sql};"

    try:
        with engine.connect() as conn:
            result = conn.execute(text(explain_query)).fetchone()
            if not result or not result[0]:
                return False, "Failed to retrieve EXPLAIN plan from MySQL", {}
            plan_data = json.loads(result[0])

        query_cost, total_rows, has_full_scan = parse_mysql_explain(plan_data)

        # Reject if total estimated row scans exceed threshold
        if total_rows > max_rows:
            return (
                False,
                f"Query rejected: Estimated row scan ({total_rows}) exceeds safety limit ({max_rows}).",
                plan_data,
            )

        # Reject if optimizer cost exceeds threshold
        if query_cost > max_cost:
            return (
                False,
                f"Query rejected: Optimizer cost ({query_cost:.2f}) exceeds safety limit ({max_cost:.2f}).",
                plan_data,
            )

        return True, f"Query plan approved (Cost: {query_cost:.2f}, Rows: {total_rows})", plan_data

    except Exception as db_err:
        return False, f"Database error during EXPLAIN: {db_err}", {}


# LangGraph Node 9 function wrapper
def query_safety_gate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    raw_sql = state.get("raw_sql", "")
    retry_count = state.get("retry_count", 0)

    if not raw_sql:
        return {
            **state,
            "sql_error": "No SQL query provided in state ('raw_sql' is empty).",
            "retry_count": retry_count + 1,
            "next_node": "sql_generator",
        }

    # Step 1: Validate and inject safe LIMIT
    ok, limited_sql, err = validate_limit(raw_sql)
    if not ok:
        new_retry = retry_count + 1
        return {
            **state,
            "sql_error": err,
            "retry_count": new_retry,
            "next_node": "sql_generator" if new_retry < 3 else "final_presentation",
        }

    # Step 2: Validate optimizer cost via MySQL EXPLAIN
    engine = get_mysql_engine()
    safe, msg, plan = validate_and_explain(limited_sql, engine=engine)

    if not safe:
        new_retry = retry_count + 1
        return {
            **state,
            "sql_error": msg,
            "retry_count": new_retry,
            "next_node": "sql_generator" if new_retry < 3 else "final_presentation",
        }

    # Step 3: Approved query moves to execution
    return {
        **state,
        "raw_sql": limited_sql,
        "sql_error": None,
        "next_node": "safe_execution",
    }


# Conditional router after Node 9
def route_after_safety_gate(state: Dict[str, Any]) -> str:
    sql_error = state.get("sql_error")
    retry_count = state.get("retry_count", 0)

    if not sql_error:
        return "safe_execution"

    if retry_count < 3:
        return "sql_generator"

    return "final_presentation"


# Local test runner
if __name__ == "__main__":
    print("=" * 70)
    print("NODE 9: QUERY SAFETY GATE TEST (MYSQL 8.0)")
    print("=" * 70)

    # Test 1: Auto-inject LIMIT 100 when missing
    sql_no_limit = "SELECT company_name FROM customers WHERE is_deleted = 0"
    ok, new_sql, err = validate_limit(sql_no_limit)
    print(f"\n[Test 1] Missing LIMIT injected:\n{new_sql}")

    # Test 2: Clamp excessive LIMIT
    sql_high_limit = "SELECT * FROM orders LIMIT 99999"
    ok, clamped_sql, err = validate_limit(sql_high_limit, max_limit=1000)
    print(f"\n[Test 2] High LIMIT clamped:\n{clamped_sql}")

    # Test 3: MySQL EXPLAIN JSON parser verification
    mock_explain_plan = {
        "query_block": {
            "select_id": 1,
            "cost_info": {"query_cost": "150.25"},
            "table": {
                "table_name": "orders",
                "access_type": "ref",
                "rows_examined_per_scan": 420,
            },
        }
    }
    cost, rows, full_scan = parse_mysql_explain(mock_explain_plan)
    print(f"\n[Test 3] MySQL Plan Parser -> Cost: {cost}, Rows: {rows}, Full Scan: {full_scan}")
