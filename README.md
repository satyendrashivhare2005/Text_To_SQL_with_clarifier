# 🚀 Enterprise Ambiguity-Aware Text-to-SQL Engine
### *With LangGraph Human-In-The-Loop Clarification & 3-Layer Defense-in-Depth*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![MySQL 8.0](https://img.shields.io/badge/Dialect-MySQL_8.0-4479A1.svg)](https://www.mysql.com/)
[![SQLGlot](https://img.shields.io/badge/AST_Guardrail-SQLGlot-purple.svg)](https://github.com/tobymao/sqlglot)

---

## 📌 Executive Summary

Most open-source Text-to-SQL solutions suffer from a fatal flaw in enterprise environments: **they guess when business terms are ambiguous**. If a user asks *"Show me revenue by customer"*, standard LLMs blindly pick a column—often mixing up **Gross Revenue**, **Net Revenue**, or **Collected Cash**—leading to silent analytical errors and flawed executive decisions.

This project implements a **production-grade, 12-node Text-to-SQL agent** built on **LangGraph**, **Pydantic**, **Groq (LLaMA-3.3 70B)**, and **MySQL 8.0**. Instead of hallucinating, the engine detects business ambiguities deterministically in 0.001 ms, pauses execution using LangGraph's **`interrupt()`** mechanism, requests human clarification through interactive UI components, and resumes execution seamlessly using **`Command(resume=...)`**.

---

## 🏗️ System Architecture

![Pipeline Graph](pipeline_graph.png)

```
[START]
   │
   ▼
Node 0: Conversational Context Loader (Pronouns & Ellipsis resolution)
   │
   ▼
Node 1: Intent & Slot Extractor (QuerySpec Pydantic Schema)
   │
   ▼
Node 2: Schema & Value Linker (ChromaDB Vector Retrieval + MySQL LIKE)
   │
   ▼
Node 3: Ambiguity Detector (Deterministic Registry Rules)
   ├── (Ambiguous) ──► Node 4: Clarifier (interrupt) ──► Node 6: Spec Resolver ──┐
   └── (Clear) ──────► Node 5: Pass-Through ────────────────────────────────────┴──► Node 7: MySQL 8.0 Generator ◄──────┐
                                                                                           │ (Regenerate)          │ (Retry)
                                                                                           ▼                       │
                                                                                   Node 8: AST Validator ──────────┤
                                                                                           │ (Valid)               │
                                                                                           ▼                       │
                                                                                   Node 9: Safety Gate (EXPLAIN) ──┤
                                                                                           │ (Safe)                │
                                                                                           ▼                       │
                                                                                   Node 10: Safe Execution ────────┘
                                                                                           │ (Success / Max Retries)
                                                                                           ▼
                                                                                   Node 11: JSON Result Formatter
                                                                                           │
                                                                                           ▼
                                                                                         [END]
```

---

## 🧠 The 12-Node Agent Pipeline

| Node | Name | File | Role & Implementation |
| :---: | :--- | :--- | :--- |
| **0** | **Context Loader** | `contextlaoder_Node_0.py` | Resolves multi-turn conversational pronouns (*"What about last month?"* $\rightarrow$ standalone question). |
| **1** | **Intent Extractor** | `Node_1.py` | Extracts explicit slots into `QuerySpec` Pydantic model using `llm.with_structured_output()`. |
| **2** | **Schema & Value Linker** | `Node_2.py` | Retrieves candidate tables via ChromaDB embeddings and performs live parameterized MySQL `LIKE` queries for entity validation. |
| **3** | **Ambiguity Detector** | `ambiguity_detector.py` | **100% deterministic (0.001ms)** pure Python rule engine. Detects 5 ambiguity classes without LLM token waste. |
| **4** | **Clarifier (HITL)** | `Node_4.py` | Triggers LangGraph **`interrupt(payload)`**, pausing graph execution and sending options to UI. |
| **5** | **Pass-Through** | `Node_5.py` | Zero-latency bypass when `confidence_score == 1.0` and zero ambiguities exist. |
| **6** | **Spec Resolver** | `Node_6.py` | Wakes up on `Command(resume=choices)`, applies rules from `semantic_registry.yaml`, and locks formulas into `QuerySpec`. |
| **7** | **MySQL Generator** | `Node_7.py` | Dialect-exact MySQL 8.0 generator using few-shot prompt, canonical join paths, and `ONLY_FULL_GROUP_BY` enforcement. |
| **8** | **AST Validator** | `Node_8.py` | Parses SQLGlot AST. Strictly enforces `SELECT`-only, blocks accidental Cartesian joins (missing `ON`), and validates columns against DDL schema. |
| **9** | **Safety Gate** | `Node_9.py` | Auto-injects `LIMIT 100` if missing via AST, and executes dry-run `EXPLAIN FORMAT=JSON` to guard against full-table scans ($> 50,000$ rows). |
| **10** | **Safe Execution** | `Node_10.py` | Executes on a read-only transaction pool (`SET TRANSACTION READ ONLY`) with a strict `MAX_EXECUTION_TIME(5000)` timeout. Up to 3 automatic repairs. |
| **11** | **Result Formatter** | `Node_11.py` | Pure Python JSON-first formatter. Produces structured payload confirming applied business definitions. |

---

## 🛡️ 3-Layer Defense-in-Depth Architecture

Even if an LLM generates a syntactically correct query, it could still be dangerous or bring down a production database. We implement a rigorous **three-tier safety barrier**:

1. **Static AST Guardrail (Node 8)**:
   * Rejects non-`SELECT` statements (`DROP`, `UPDATE`, `DELETE`, `TRUNCATE`).
   * Blocks Cartesian joins (`JOIN` without `ON`).
   * Verifies all column identifiers against candidate table DDL schema using SQLGlot's `qualify` optimizer.
2. **Cost & Optimizer Guardrail (Node 9)**:
   * Auto-injects `LIMIT 100` into unbounded queries.
   * Runs `EXPLAIN FORMAT=JSON` against MySQL optimizer to calculate estimated row scan and query cost.
   * Rejects unindexed full table scans over $50,000$ rows and loops back to Node 7 for tighter date filters.
3. **Runtime Execution Guardrail (Node 10)**:
   * Session locked to `SET TRANSACTION READ ONLY;`.
   * Strict 5-second optimizer timeout hint: `SELECT /*+ MAX_EXECUTION_TIME(5000) */ ...`.
   * Automatically intercepts runtime exceptions (e.g. `ONLY_FULL_GROUP_BY`, division by zero) and feeds back error diagnostics to Node 7 for self-correction.

---

## ⚙️ Ambiguity Detection Rules (`semantic_registry.yaml`)

The engine catches **5 distinct ambiguity types**:

```yaml
# 1. Column Collision: Two identical column names in different tables
column_collisions:
  revenue:
    clarification_prompt: "Which definition of revenue would you like to use?"
    options:
      net_revenue: "Net Revenue: SUM(gross_amount - discount_amount)"
      gross_revenue: "Gross Revenue: SUM(gross_amount)"
      collected_revenue: "Collected Cash: SUM(payments.paid_amount)"

# 2. Undefined Metric: Colloquial business words
undefined_metric:
  top_customers:
    clarification_prompt: "How should 'top customers' be ranked?"
    options:
      by_order_count: "By total number of orders placed"
      by_net_revenue: "By total net monetary spend"

# 3. Missing Filter: Large transaction tables queried without time windows
missing_filter_rules:
  orders:
    threshold_rows: 100000
    clarification_prompt: "The `orders` table is large. Which time period should I filter by?"
    options:
      last_30_days: "Last 30 days"
      last_quarter: "Last calendar quarter"
      year_to_date: "Year to date"
```

---

## 🚀 Quickstart Guide

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/satyendrashivhare2005/Text_To_SQL_with_clarifier.git
cd Text_To_SQL_with_clarifier

python3 -m venv myenv
source myenv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file from the example template:

```bash
cp .env.example .env
```

Add your Groq API key:
```env
GROQ_API_KEY=gsk_your_actual_groq_api_key_here
MYSQL_DATABASE_URL=mysql+pymysql://root:password@localhost:3306/ecommerce_db
API_URL=http://localhost:8000
```
*(Note: If no MySQL instance is running, the engine automatically falls back to offline mock mode for testing without crashing!)*

### 3. Start the FastAPI Backend

```bash
python api.py
```
* **API Server:** http://localhost:8000
* **Interactive Swagger Docs:** http://localhost:8000/docs

### 4. Start the Streamlit Frontend

In a second terminal window:

```bash
streamlit run app.py
```
* **Web UI:** http://localhost:8501

---

## 📡 API Reference

### `POST /api/query`
Initiates a query through the LangGraph pipeline.

**Request:**
```json
{
  "question": "Show me top 5 enterprise customers by revenue"
}
```

**Response (If Ambiguous - Node 4 Pauses):**
```json
{
  "status": "clarification_needed",
  "thread_id": "sess_53ba1d8a",
  "clarification": {
    "clarifications": [
      {
        "trigger_term": "orders",
        "clarification_prompt": "The `orders` table is large. Which time period should I filter by?",
        "options": {
          "last_7_days": "Last 7 days",
          "last_30_days": "Last 30 days",
          "last_quarter": "Last calendar quarter"
        }
      }
    ]
  }
}
```

---

### `POST /api/clarify`
Resumes a paused execution thread with the user's selected choice.

**Request:**
```json
{
  "thread_id": "sess_53ba1d8a",
  "choices": {
    "orders": "last_30_days",
    "enterprise": "Enterprise"
  }
}
```

**Response (Completed - Node 11):**
```json
{
  "status": "completed",
  "thread_id": "sess_53ba1d8a",
  "result": {
    "status": "success",
    "summary": "Retrieved 3 matching records.",
    "row_count": 3,
    "data": [
      { "company_name": "Acme Corp", "net_revenue": 145000.0 },
      { "company_name": "GlobalTech", "net_revenue": 98500.5 }
    ],
    "sql": "SELECT customers.company_name, SUM(orders.gross_amount - orders.discount_amount) AS revenue FROM customers INNER JOIN orders ON customers.customer_id = orders.customer_id WHERE customers.customer_tier = 'Enterprise' AND orders.created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY) GROUP BY customers.customer_id, customers.company_name ORDER BY revenue DESC LIMIT 5;"
  }
}
```

---

## 💻 Tech Stack

* **Orchestration**: [LangGraph](https://github.com/langchain-ai/langgraph) (StateGraph with `MemorySaver` checkpointing, `interrupt`, and `Command(resume)`)
* **LLM Engine**: [Groq](https://groq.com/) with LLaMA-3.3-70B-Versatile
* **Data Validation**: [Pydantic v2](https://docs.pydantic.dev/)
* **SQL Parsing & Optimization**: [SQLGlot](https://github.com/tobymao/sqlglot)
* **Database & Pooling**: [SQLAlchemy 2.0](https://www.sqlalchemy.org/) & MySQL 8.0
* **Vector Store**: [ChromaDB](https://www.trychroma.com/) (Schema and synonym embeddings)
* **Serving**: [FastAPI](https://fastapi.tiangolo.com/) & [Uvicorn](https://www.uvicorn.org/)
* **UI**: [Streamlit](https://streamlit.io/)

---

## 📄 License

MIT License. Free for commercial and open-source use.
