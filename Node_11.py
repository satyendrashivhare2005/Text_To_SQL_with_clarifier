import json
from typing import Any, Dict, List, Optional


# Build transparent, structured explanation without LLM overhead
def build_response_payload(
    rows: List[Dict[str, Any]],
    raw_sql: str,
    spec: Any = None,
    sql_error: Optional[str] = None,
) -> Dict[str, Any]:
    # Handle error scenario when retries are exhausted
    if sql_error and not rows:
        return {
            "status": "error",
            "summary": "Query execution failed after self-correction retries.",
            "error": sql_error,
            "sql": raw_sql,
            "row_count": 0,
            "data": [],
            "applied_clarifications": {},
        }

    # Extract user clarification choices
    clarifications: Dict[str, str] = {}
    if spec and hasattr(spec, "resolved_choices") and spec.resolved_choices:
        clarifications = dict(spec.resolved_choices)

    # Extract any safe default assumptions made
    assumptions: List[str] = []
    if spec and hasattr(spec, "assumptions_made") and spec.assumptions_made:
        assumptions = list(spec.assumptions_made)

    # Formulate concise natural summary
    row_count = len(rows)
    if row_count > 0:
        summary = f"Retrieved {row_count} matching records."
    else:
        summary = "Query executed successfully, but returned 0 matching records."

    return {
        "status": "success",
        "summary": summary,
        "row_count": row_count,
        "data": rows,
        "sql": raw_sql,
        "applied_clarifications": clarifications,
        "assumptions": assumptions,
    }


# LangGraph Node 11 wrapper
def result_formatter_node(state: Dict[str, Any]) -> Dict[str, Any]:
    rows = state.get("query_results", [])
    raw_sql = state.get("raw_sql", "")
    spec = state.get("query_spec")
    sql_error = state.get("sql_error")

    # Generate structured JSON-ready dictionary
    response_payload = build_response_payload(
        rows=rows,
        raw_sql=raw_sql,
        spec=spec,
        sql_error=sql_error,
    )

    # Serialize to JSON string for state compatibility while preserving dictionary
    return {
        **state,
        "final_response": json.dumps(response_payload, indent=2),
        "next_node": None,
    }


# Local test runner
if __name__ == "__main__":
    print("=" * 70)
    print("NODE 11: JSON-FIRST RESULT FORMATTER TEST (NO LLM)")
    print("=" * 70)

    sample_rows = [
        {"company_name": "Acme Corp", "net_revenue": 145000.00},
        {"company_name": "GlobalTech", "net_revenue": 98500.50},
    ]
    sample_sql = "SELECT company_name, SUM(net_amount) AS net_revenue FROM customers GROUP BY company_name LIMIT 2;"

    # Mock QuerySpec object
    class MockSpec:
        resolved_choices = {"revenue": "net_revenue"}
        assumptions_made = ["Filtered out cancelled orders"]

    result = build_response_payload(sample_rows, sample_sql, spec=MockSpec())
    print("\n[Structured JSON Payload for FastAPI]:")
    print(json.dumps(result, indent=2))
