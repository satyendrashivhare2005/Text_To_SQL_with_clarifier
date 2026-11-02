import re
from typing import Any, Dict, Optional, Tuple, Set
import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify


def ddl_to_schema(ddl_str: str) -> Dict[str, Dict[str, str]]:
    """
    Parses CREATE TABLE DDL statements into a SQLGlot schema dictionary:
    {
        "customers": {
            "customer_id": "BIGINT",
            "company_name": "VARCHAR",
            "customer_tier": "VARCHAR", ...
        },
        "orders": {
            "order_id": "BIGINT",
            "gross_amount": "DECIMAL", ...
        }
    }
    """
    schema: Dict[str, Dict[str, str]] = {}
    if not ddl_str or not ddl_str.strip():
        return schema

    # Filter out pure SQL comments (-- ...) to avoid parser noise
    clean_lines = [
        line for line in ddl_str.splitlines()
        if not line.strip().startswith("--")
    ]
    cleaned_ddl = "\n".join(clean_lines)

    try:
        statements = sqlglot.parse(cleaned_ddl, read="mysql")
    except Exception:
        return schema

    for stmt in statements:
        if not stmt:
            continue
        # Check for CREATE TABLE statement
        if isinstance(stmt, exp.Create):
            table_node = stmt.find(exp.Table)
            if not table_node:
                continue
            table_name = table_node.name.lower()

            columns: Dict[str, str] = {}
            for col_def in stmt.find_all(exp.ColumnDef):
                col_name = col_def.name.lower()
                col_type = str(col_def.kind) if col_def.kind else "TEXT"
                columns[col_name] = col_type

            if columns:
                schema[table_name] = columns

    return schema

def verify_sql(
    query: str,
    schema_dict: Optional[Dict[str, Dict[str, str]]] = None,
    dialect: str = "mysql",
) -> Tuple[bool, Optional[str]]:
    """
    Validates a SQL query using SQLGlot AST:
    1. Syntax Check: Validates MySQL 8.0 parseability.
    2. Read-Only Security Gate: Ensures only SELECT statements; blocks DML/DDL.
    3. Accidental Cartesian Join Check: Verifies all non-CROSS joins have an ON condition.
    4. Table & Column Existence: Verifies tables and columns against schema_dict.
    """
    if not query or not query.strip():
        return False, "Validation Error: SQL query is empty."

    # --------------------------------------------------------------------------
    # CHECK 1: SYNTAX PARSING
    # --------------------------------------------------------------------------
    try:
        parsed = sqlglot.parse_one(query, read=dialect)
    except ParseError as e:
        return False, f"SQL Syntax Error: {str(e)}"
    except Exception as e:
        return False, f"Failed to parse SQL: {str(e)}"

    if not parsed:
        return False, "Validation Error: SQLGlot returned empty AST."

    # --------------------------------------------------------------------------
    # CHECK 2: SECURITY & READ-ONLY ENFORCEMENT
    # --------------------------------------------------------------------------
    # Root expression must be a SELECT statement
    if not isinstance(parsed, exp.Select):
        return (
            False,
            "Security Violation: Only SELECT queries are permitted. "
            "INSERT, UPDATE, DELETE, and DDL statements are strictly blocked.",
        )

    # Scan for any nested destructive expressions
    prohibited_types = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Alter,
        exp.Command,
    )
    for expr in parsed.find_all(prohibited_types):
        return (
            False,
            f"Security Violation: Prohibited statement detected ({type(expr).__name__}).",
        )

    # --------------------------------------------------------------------------
    # CHECK 3: ACCIDENTAL CARTESIAN JOIN CHECK
    # --------------------------------------------------------------------------
    for join in parsed.find_all(exp.Join):
        is_cross = False
        if join.kind and "CROSS" in str(join.kind).upper():
            is_cross = True
        if join.args.get("method") and "CROSS" in str(join.args.get("method")).upper():
            is_cross = True

        if not join.args.get("on") and not is_cross:
            target_tbl = join.this.name if hasattr(join.this, "name") else str(join.this)
            return (
                False,
                f"Invalid Join: JOIN on table '{target_tbl}' is missing an ON condition. "
                "Accidental Cartesian joins (unconstrained cross products) are blocked.",
            )

    if schema_dict:
        valid_tables = {tbl.lower() for tbl in schema_dict.keys()}

        # Verify referenced tables
        used_tables: Set[str] = set()
        for tbl in parsed.find_all(exp.Table):
            if tbl.name:
                used_tables.add(tbl.name.lower())

        unknown_tables = [t for t in used_tables if t not in valid_tables]
        if unknown_tables:
            return (
                False,
                f"Schema Validation Error: Unknown table(s) {unknown_tables} referenced. "
                f"Allowed candidate tables: {sorted(list(valid_tables))}.",
            )

        # Verify columns and ambiguities using SQLGlot qualify optimizer
        try:
            # qualify resolves table aliases and validates columns against schema_dict
            qualify(
                parsed.copy(),
                schema=schema_dict,
                dialect=dialect,
            )
        except OptimizeError as e:
            return (
                False,
                f"Schema Validation Error: {str(e)}. "
                "Please verify that all referenced columns exist in the candidate tables.",
            )
        except Exception as e:
            return False, f"Schema Qualification Error: {str(e)}"

    return True, None

def sql_validator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph Node 8: SQLGlot AST & Schema Validator.
    Reads state["raw_sql"], state["linked_schema_ddl"], and state.get("retry_count", 0).
    Updates state["sql_error"] and state["retry_count"].
    """
    raw_sql = state.get("raw_sql", "")
    linked_schema_ddl = state.get("linked_schema_ddl", "")
    retry_count = state.get("retry_count", 0)

    if not raw_sql:
        return {
            **state,
            "sql_error": "No SQL query provided in state ('raw_sql' is empty).",
            "retry_count": retry_count + 1,
            "next_node": "sql_generator",
        }

    # Build schema dictionary from candidate DDL
    schema_dict = ddl_to_schema(linked_schema_ddl)

    # Run complete AST and Schema validation
    is_valid, error_message = verify_sql(
        raw_sql, schema_dict=schema_dict, dialect="mysql"
    )

    if not is_valid:
        new_retry_count = retry_count + 1
        return {
            **state,
            "sql_error": error_message,
            "retry_count": new_retry_count,
            "next_node": "sql_generator" if new_retry_count < 3 else "final_presentation",
        }

    # Query is valid!
    return {
        **state,
        "sql_error": None,
        "next_node": "query_safety_gate",
    }

def route_after_sql_validator(state: Dict[str, Any]) -> str:
    """
    LangGraph Conditional Edge router after Node 8:
    - If valid (sql_error is None) -> 'query_safety_gate' (Node 9)
    - If error and retry_count < 3 -> 'sql_generator' (Node 7 self-correction)
    - If retry_count >= 3 -> 'final_presentation' (Node 11 graceful failure)
    """
    sql_error = state.get("sql_error")
    retry_count = state.get("retry_count", 0)

    if not sql_error:
        return "query_safety_gate"

    if retry_count < 3:
        return "sql_generator"

    return "final_presentation"


