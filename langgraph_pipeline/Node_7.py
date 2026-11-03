from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml
from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from QuerySpec import FilterCondition, OrderBySpec, QuerySpec

load_dotenv()
NODE_7_SYSTEM_PROMPT = """You are Node 7 (MySQL 8.0 Generator) in a high-precision Text-to-SQL engine.
Your role is to translate a structured, fully resolved `QuerySpec` into an executable, performant MySQL 8.0 SQL query.

### DATABASE ENGINE & DIALECT RULES:
1. **Target Dialect**: MySQL 8.0.
   - Use standard MySQL date functions: `CURRENT_DATE()`, `DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)`, `DATE_FORMAT()`.
   - Strictly adhere to `ONLY_FULL_GROUP_BY`: Every non-aggregated column in the `SELECT` list must be included in the `GROUP BY` clause.
2. **Security & Read-Only**:
   - Generate `SELECT` statements ONLY.
   - Never generate `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, or multiple semicolon-separated statements.
3. **Explicit Joins**:
   - Always use explicit `INNER JOIN` or `LEFT JOIN` with `ON` conditions.
   - NEVER use implicit comma joins (`FROM table_a, table_b`). Follow the provided Canonical Joins.
4. **Respect Resolved Choices & Formulas**:
   - Look at `resolved_choices` and `assumptions_made` in the QuerySpec.
   - If revenue was resolved as `net_revenue`, use: `SUM(orders.gross_amount - orders.discount_amount)`.
   - If revenue was resolved as `gross_revenue`, use: `SUM(orders.gross_amount)`.
   - If revenue was resolved as `collected_revenue`, use: `SUM(payments.paid_amount)` and join `payments`.
5. **Global Safe Defaults**:
   - Unless the user explicitly asked for deleted records or cancelled orders:
     - Apply: `customers.is_deleted = 0` (if `customers` table is used).
     - Apply: `orders.order_status NOT IN ('cancelled', 'refunded')` (if `orders` table is used).
6. **Output Format**:
   - Return ONLY the executable SQL query.
   - Do NOT wrap in markdown formatting (no ```sql or ```).
   - Do NOT include any explanations, greetings, or commentary.

### DATABASE SCHEMA (DDL):
{table_schemas}

### CANONICAL JOIN PATHS:
{canonical_joins}

### FEW-SHOT EXAMPLES:

--- Example 1: Grouping with Metric & Ordering ---
QuerySpec (JSON):
{{
  "raw_question": "Show me top 5 premium customers by revenue",
  "metrics": ["revenue"],
  "entities": ["customers", "orders"],
  "groupings": ["customers.company_name"],
  "filters": [{{"field_or_dimension": "customer_tier", "operator": "=", "value": "Enterprise"}}],
  "order_by": {{"field_or_metric": "revenue", "direction": "DESC", "limit": 5}},
  "resolved_choices": {{"revenue": "net_revenue", "customer_tier": "Enterprise"}}
}}

Generated SQL:
SELECT 
    `customers`.`company_name`,
    SUM(`orders`.`gross_amount` - `orders`.`discount_amount`) AS `net_revenue`
FROM `customers`
INNER JOIN `orders` 
    ON `customers`.`customer_id` = `orders`.`customer_id`
WHERE `customers`.`customer_tier` = 'Enterprise'
  AND `customers`.`is_deleted` = 0
  AND `orders`.`order_status` NOT IN ('cancelled', 'refunded')
GROUP BY `customers`.`customer_id`, `customers`.`company_name`
ORDER BY `net_revenue` DESC
LIMIT 5;

--- Example 2: Filtering with Date Window ---
QuerySpec (JSON):
{{
  "raw_question": "How many completed orders did we have in the last 30 days?",
  "metrics": ["order_count"],
  "entities": ["orders"],
  "time_window": "last 30 days",
  "filters": [{{"field_or_dimension": "order_status", "operator": "=", "value": "completed"}}]
}}

Generated SQL:
SELECT 
    COUNT(`orders`.`order_id`) AS `order_count`
FROM `orders`
WHERE `orders`.`order_status` = 'completed'
  AND `orders`.`created_at` >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
"""

NODE_7_HUMAN_PROMPT = """{error_context}
Query Specification to Convert:
{query_spec}

Generate the final MySQL 8.0 SQL query:"""

NODE_7_PROMPT = ChatPromptTemplate.from_messages([
    ("system", NODE_7_SYSTEM_PROMPT),
    ("human", NODE_7_HUMAN_PROMPT),
])


def find_registry_file(path_input: Optional[Union[str, Path]] = None) -> Path:
    candidates = []
    if path_input:
        p = Path(path_input)
        candidates.extend([p, Path(__file__).parent / p.name])
    pkg_dir = Path(__file__).parent
    candidates.extend([
        pkg_dir / "sematic_registry.yaml",
        pkg_dir / "semantic_registry.yaml",
        Path("sematic_registry.yaml"),
        Path("semantic_registry.yaml"),
    ])
    for c in candidates:
        if c.exists():
            return c
    return pkg_dir / "sematic_registry.yaml"


def load_canonical_joins(registry_path: Optional[Union[str, Path]] = None) -> str:
    """Extracts canonical join paths from sematic_registry.yaml."""
    path = find_registry_file(registry_path)
    with open(path, "r", encoding="utf-8") as f:
        reg = yaml.safe_load(f) or {}

    joins = reg.get("canonical_joins", [])
    lines = []
    for j in joins:
        lines.append(
            f"- {j['left_table']} {j['join_type']} {j['right_table']} ON {j['on_condition']}"
        )
    return "\n".join(lines) if lines else "None specified."


# Initialize LLM with temperature=0 for deterministic SQL generation
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
)

sql_generator_chain = NODE_7_PROMPT | llm | StrOutputParser()


def generate_sql(
    spec: QuerySpec,
    linked_schema_ddl: str,
    error_context: str = "",
    registry_path: str = "sematic_registry.yaml",
) -> str:
    """
    Passes the whole QuerySpec as formatted JSON into the prompt,
    along with the DDL and canonical joins, returning clean SQL.
    """
    canonical_joins_str = load_canonical_joins(registry_path)

    # 1. Prepare error context for self-correction retries
    err_block = ""
    if error_context:
        err_block = (
            f"⚠️ PREVIOUS ATTEMPT FAILED WITH THIS ERROR:\n{error_context}\n"
            f"Please FIX this error in your new SQL query.\n\n"
        )

    # 2. Convert entire QuerySpec to clean, formatted JSON
    query_spec_json = spec.model_dump_json(indent=2)

    # 3. Invoke LLM chain
    raw_output = sql_generator_chain.invoke({
        "table_schemas": linked_schema_ddl or "No DDL provided.",
        "canonical_joins": canonical_joins_str,
        "error_context": err_block,
        "query_spec": query_spec_json,
    })

    # 4. Clean any accidental markdown code blocks
    clean_sql = (
        raw_output.replace("```sql", "")
        .replace("```", "")
        .strip()
        .rstrip(";")
        + ";"
    )
    return clean_sql


# ==============================================================================
# LANGGRAPH NODE 7 FUNCTION WRAPPER
# ==============================================================================
def sql_generator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph Node 7: MySQL 8.0 Generator.
    Reads state["query_spec"], state["linked_schema_ddl"], and state.get("sql_error").
    Writes state["raw_sql"].
    """
    spec: QuerySpec = state.get("query_spec")
    if not spec:
        raise ValueError("State is missing 'query_spec'")

    schema_ddl: str = state.get("linked_schema_ddl", "")
    sql_error: str = state.get("sql_error", "")

    generated_sql = generate_sql(
        spec=spec,
        linked_schema_ddl=schema_ddl,
        error_context=sql_error,
    )

    return {
        **state,
        "raw_sql": generated_sql,
        "sql_error": None,  # Reset prior error once regenerated
        "next_node": "sql_validator_node",  # Node 8 (SQLGlot AST Validator)
    }


# ==============================================================================
# LOCAL TEST RUNNER
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("NODE 7: MYSQL 8.0 GENERATOR TEST")
    print("=" * 70)

    sample_ddl = """
    CREATE TABLE customers (
        customer_id BIGINT PRIMARY KEY,
        company_name VARCHAR(255) NOT NULL,
        customer_tier VARCHAR(50) NOT NULL,
        is_deleted BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE orders (
        order_id BIGINT PRIMARY KEY,
        customer_id BIGINT NOT NULL,
        gross_amount DECIMAL(12, 2) NOT NULL,
        discount_amount DECIMAL(12, 2) NOT NULL,
        order_status VARCHAR(50) NOT NULL,
        created_at DATETIME NOT NULL
    );
    """.strip()

    test_spec = QuerySpec(
        raw_question="Show me top 5 premium customers by revenue",
        metrics=["revenue"],
        entities=["customers", "orders"],
        groupings=["customers.company_name"],
        filters=[
            FilterCondition(
                field_or_dimension="customer_tier",
                operator="=",
                value="Enterprise",
            )
        ],
        order_by=OrderBySpec(field_or_metric="revenue", direction="DESC", limit=5),
        resolved_choices={"revenue": "net_revenue", "customer_tier": "Enterprise"},
        assumptions_made=[
            "Resolved revenue as Net Revenue: SUM(orders.gross_amount - orders.discount_amount)"
        ],
    )

    try:
        sql = generate_sql(test_spec, linked_schema_ddl=sample_ddl)
        print("\nGenerated MySQL 8.0 Query:")
        print(sql)
    except Exception as e:
        print(f"\nExecution skipped or API key needed: {e}")
