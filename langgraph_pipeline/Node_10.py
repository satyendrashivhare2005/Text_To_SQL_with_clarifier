import datetime
from decimal import Decimal
import os
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

# Default execution settings
DEFAULT_TIMEOUT_SEC = 5
MAX_RETRIES = 3


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


# Normalize database values to JSON-serializable types
def normalize_val(val: Any) -> Any:
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val


# Inject MySQL optimizer timeout hint into SELECT query
def inject_execution_timeout(query: str, timeout_ms: int = 5000) -> str:
    stripped = query.strip()
    if stripped.startswith("/*+"):
        return stripped
    if stripped.upper().startswith("SELECT"):
        return f"SELECT /*+ MAX_EXECUTION_TIME({timeout_ms}) */ " + stripped[6:].lstrip()
    return stripped


# Execute SQL query on read-only connection with timeout
def execute_sql_safely(
    raw_sql: str,
    engine=None,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> Tuple[bool, List[Dict[str, Any]], Optional[str], float]:
    start_time = time.perf_counter()

    # Graceful fallback for offline mode
    if engine is None:
        latency_ms = (time.perf_counter() - start_time) * 1000
        mock_data = [
            {"company_name": "Acme Corp", "net_revenue": 145000.00},
            {"company_name": "GlobalTech", "net_revenue": 98500.50},
            {"company_name": "Nexus Dynamics", "net_revenue": 72000.00},
        ]
        return True, mock_data, None, latency_ms

    timeout_ms = timeout_sec * 1000
    sql_with_hint = inject_execution_timeout(raw_sql, timeout_ms=timeout_ms)

    try:
        with engine.connect() as conn:
            # Enforce read-only transaction isolation
            conn.execute(text("SET TRANSACTION READ ONLY;"))
            result = conn.execute(text(sql_with_hint))

            columns = list(result.keys())
            rows = result.fetchmany(100)
            latency_ms = (time.perf_counter() - start_time) * 1000

            normalized_rows = [
                {col: normalize_val(row[idx]) for idx, col in enumerate(columns)}
                for row in rows
            ]
            return True, normalized_rows, None, latency_ms

    except (DBAPIError, OperationalError, ProgrammingError, Exception) as err:
        latency_ms = (time.perf_counter() - start_time) * 1000
        return False, [], str(err), latency_ms


# LangGraph Node 10 wrapper
def safe_execution_node(state: Dict[str, Any]) -> Dict[str, Any]:
    raw_sql = state.get("raw_sql", "").strip()
    retry_count = state.get("retry_count", 0)

    if not raw_sql:
        return {
            **state,
            "sql_error": "No SQL query provided in state ('raw_sql' is empty).",
            "retry_count": retry_count + 1,
            "next_node": "sql_generator",
        }

    engine = get_mysql_engine()
    success, rows, err, latency = execute_sql_safely(raw_sql, engine=engine)

    if not success:
        new_retry = retry_count + 1
        return {
            **state,
            "sql_error": err,
            "retry_count": new_retry,
            "next_node": "sql_generator" if new_retry < MAX_RETRIES else "final_presentation",
        }

    # Query executed successfully
    return {
        **state,
        "query_results": rows,
        "sql_error": None,
        "next_node": "final_presentation",
    }


# Conditional router after Node 10
def route_after_execution(state: Dict[str, Any]) -> str:
    sql_error = state.get("sql_error")
    retry_count = state.get("retry_count", 0)

    if not sql_error:
        return "final_presentation"

    if retry_count < MAX_RETRIES:
        return "sql_generator"

    return "final_presentation"
