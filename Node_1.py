import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from QuerySpec import QuerySpec
from contextlaoder_Node_0 import resolve_conversation_context, conversation_context_node


load_dotenv()  

# 2. Structured prompt for Node 1 (Semantic Intent Parser)
TABLE_SCHEMAS = """
CREATE TABLE customers (
    customer_id VARCHAR(64) PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    customer_tier VARCHAR(32) NOT NULL, -- Allowed: 'Enterprise', 'Mid-Market', 'SMB'
    country VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE orders (
    order_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) REFERENCES customers(customer_id),
    product_id VARCHAR(64) REFERENCES products(product_id),
    gross_amount DECIMAL(12, 2) NOT NULL,
    net_amount DECIMAL(12, 2) NOT NULL,
    tax_amount DECIMAL(12, 2) NOT NULL,
    order_status VARCHAR(32) NOT NULL,
    order_date DATE NOT NULL,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE TABLE products (
    product_id VARCHAR(64) PRIMARY KEY,
    product_name VARCHAR(255) NOT NULL,
    product_category VARCHAR(128) NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL
);
""".strip()

NODE_1_SYSTEM_PROMPT = """You are Node 1 (Semantic Intent Parser) of an ambiguity-aware Text-to-SQL engine.
Your ONLY job is to parse the user's natural language question into the structured `QuerySpec` schema.
Do NOT write SQL code.

### CRITICAL RULES FOR AMBIGUITY PRESERVATION (SO NODE 3 CAN CATCH THEM):
1. **Preserve Vague Metrics Verbatim**:
   - If the user says "revenue", "sales", or "income" without specifying gross or net, output `"revenue"` in `metrics`. Do NOT silently guess `orders.gross_amount` or `orders.net_amount`.
   - If the user says "top", "best", or "leading" without naming a numeric metric (e.g., "Show me top customers"), include `"top"` in `metrics` so the downstream ambiguity detector flags it.
2. **Preserve Vague Time Phrases Verbatim**:
   - If the user says "recently", "lately", or "this period", copy that exact phrase into `time_window`.
   - If the user does NOT mention any time range or date, set `time_window` to `null` (`None`). Never invent a default date filter.
3. **Preserve User Filter Values Verbatim**:
   - Extract each filter condition into `filters` with `field_or_dimension`, `operator` (`=`, `!=`, `LIKE`, `>`, `<`, `IN`), and the user's exact `value` (e.g., if the user says "premium customers", set `field_or_dimension="customer_tier"`, `operator="="`, `value="premium"`).
4. **Map Entities to Relevant Table Names**:
   - Populate `entities` with the lowercase table names required to answer the question (e.g., `["customers", "orders"]`).
5. **Leave Downstream Fields Empty**:
   - Leave `resolved_choices`, `detected_ambiguities`, and `assumptions_made` empty—those are populated by Node 3 and Node 4.

### AVAILABLE DATABASE TABLES:
{table_schemas}

### FEW-SHOT EXAMPLES:
- **User**: "Show me top 5 premium customers by revenue"
  - `metrics`: `["revenue"]`
  - `entities`: `["customers", "orders"]`
  - `groupings`: `["customers.company_name"]`
  - `filters`: `[{{"field_or_dimension": "customer_tier", "operator": "=", "value": "premium"}}]`
  - `time_window`: `null`
  - `order_by`: `{{"field_or_metric": "revenue", "direction": "DESC", "limit": 5}}`

- **User**: "How many orders did Acme place in the last 30 days?"
  - `metrics`: `["orders.order_id"]`
  - `entities`: `["customers", "orders"]`
  - `groupings`: `[]`
  - `filters`: `[{{"field_or_dimension": "company_name", "operator": "LIKE", "value": "Acme"}}]`
  - `time_window`: `"last 30 days"`
  - `order_by`: `null`
"""
Node_1_Prompt = ChatPromptTemplate.from_messages([
    ("system", NODE_1_SYSTEM_PROMPT),
    ("human", "{standalone_question}"),
])


def extract_query_spec(
    standalone_question: str,
    model_name: str = "openai/gpt-oss-20b",
    table_schemas: str = TABLE_SCHEMAS,
) -> QuerySpec:
   llm = ChatGroq(
         model=model_name,
         temperature=0,  # Always use 0 for deterministic parsing and SQL generation
   )
   structured_output = llm.with_structured_output(QuerySpec)
   intent_extractor_chain = Node_1_Prompt | structured_output

   spec = intent_extractor_chain.invoke({
         "standalone_question": standalone_question,
         "table_schemas": table_schemas,
   })

   if not getattr(spec, "raw_question", None):
      spec.raw_question = standalone_question

   return spec


def intent_extractor_node(state: Dict[str, Any]) -> Dict[str, Any]:
  standalone_question = state.get(
      "standalone_question", state.get("user_question", "")
  )
  spec = extract_query_spec(standalone_question=standalone_question)
  return {
      **state,
      "query_spec": spec,
  }

if __name__ == "__main__":
  test_q = "Show me top 5 premium customers by revenue"
  print("=" * 60)
  print(f"NODE 1 TEST: '{test_q}'")
  print("=" * 60)
  try:
    result_spec = extract_query_spec(test_q)
    print("\nParsed QuerySpec:")
    print(f"  raw_question : {result_spec.raw_question}")
    print(f"  metrics      : {result_spec.metrics}")
    print(f"  entities     : {result_spec.entities}")
    print(f"  filters      : {result_spec.filters}")
    print(f"  time_window  : {result_spec.time_window}")
    print(f"  order_by     : {result_spec.order_by}")
  except Exception as e:
    print(f"Error testing Node 1: {e}")