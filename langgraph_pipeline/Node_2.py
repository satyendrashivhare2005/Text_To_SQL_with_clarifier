from pathlib import Path
from typing import Any, Dict, List, Optional , Union
import yaml 
from QuerySpec import QuerySpec, FilterCondition, OrderBySpec, AmbiguityFlag

import chromadb
from sqlalchemy import create_engine, text , inspect


HAS_SQLALCHEMY = True
DEFAULT_TABLE_CATALOG: Dict[str, Dict[str, Any]] = {
    "customers": {
        "table_name": "customers",
        "description": (
            "Customer profiles, client accounts, organization tiers, geographic"
            " location, and active status. Use when answering questions about"
            " buyers, clients, accounts, VIP tiers, company names, or customer"
            " regions."
        ),
        "synonyms": [
            "client",
            "buyer",
            "user",
            "account",
            "company",
            "organization",
            "enterprise",
            "shopper",
        ],
        "columns": {
            "customer_id": "Primary key uniquely identifying each customer",
            "company_name": "Official business or company name of the customer",
            "customer_tier": "Segment tier: 'Enterprise', 'Mid-Market', 'SMB', 'Starter'",
            "country": "Primary country location of the customer",
            "billing_country": "Country on file for billing invoices",
            "subscription_status": "Subscription state: 'active', 'paused', 'cancelled'",
            "is_active": "Boolean flag indicating whether the account is currently active (1 = active, 0 = inactive)",
            "is_deleted": "Soft deletion flag (0 = active record, 1 = deleted/archived)",
        },
        "embedding_text": (
            "Table: customers. Domain: Customers, Accounts & Organizations."
            " Contains customer profiles, company name, client accounts,"
            " customer tier (Enterprise, Mid-Market, SMB, Starter, premium,"
            " vip), billing country, country location, subscription status, and"
            " active status. Best for questions regarding who the buyers are,"
            " customer segment, account details, and client lists."
        ),
        "ddl": (
            "CREATE TABLE customers (\n"
            "  customer_id BIGINT PRIMARY KEY,\n"
            "  company_name VARCHAR(255) NOT NULL,\n"
            "  customer_tier VARCHAR(50) NOT NULL,\n"
            "  country VARCHAR(100),\n"
            "  billing_country VARCHAR(100),\n"
            "  subscription_status VARCHAR(50) DEFAULT 'active',\n"
            "  is_active TINYINT(1) DEFAULT 1,\n"
            "  is_deleted TINYINT(1) DEFAULT 0\n"
            ");"
        ),
    },
    "orders": {
        "table_name": "orders",
        "description": (
            "E-commerce sales transactions, order placements, revenue metrics,"
            " order dates, timestamps, shipping country, and fulfillment"
            " status. Crucial for revenue, sales, order counts, and date"
            " filters."
        ),
        "synonyms": [
            "sales",
            "purchases",
            "transactions",
            "invoices",
            "deals",
            "checkouts",
            "revenue",
        ],
        "columns": {
            "order_id": "Primary key uniquely identifying each order",
            "customer_id": "Foreign key referencing customers.customer_id",
            "gross_amount": "Total monetary value before discounts, vouchers, and tax",
            "discount_amount": "Total discount deductions applied to the order",
            "net_amount": "Total monetary value after discounts, excluding tax",
            "cogs_amount": "Cost of goods sold (COGS) for calculating net profit margin",
            "tax_amount": "Sales tax or VAT applied to the transaction",
            "order_status": "Fulfillment status: 'completed', 'pending', 'cancelled', 'refunded', 'shipped'",
            "created_at": "Timestamp when the customer placed the order (checkout time)",
            "paid_at": "Timestamp when the payment cleared successfully",
            "shipped_at": "Timestamp when items were dispatched from warehouse",
            "shipping_country": "Destination country for order delivery",
            "is_deleted": "Soft deletion flag (0 = active, 1 = deleted)",
        },
        "embedding_text": (
            "Table: orders. Domain: Sales, Revenue, Transactions & Orders."
            " Contains monetary amounts (gross amount, net amount, discount"
            " amount, cogs amount, tax amount), transaction dates (created_at,"
            " paid_at, shipped_at, order date), order status (completed,"
            " cancelled, refunded), and shipping destination. Best for"
            " questions on revenue, sales figures, profit margin, total order"
            " volume, transaction history, and time periods."
        ),
        "ddl": (
            "CREATE TABLE orders (\n"
            "  order_id BIGINT PRIMARY KEY,\n"
            "  customer_id BIGINT NOT NULL,\n"
            "  gross_amount DECIMAL(12,2) NOT NULL,\n"
            "  discount_amount DECIMAL(12,2) DEFAULT 0.00,\n"
            "  net_amount DECIMAL(12,2) NOT NULL,\n"
            "  cogs_amount DECIMAL(12,2) DEFAULT 0.00,\n"
            "  tax_amount DECIMAL(12,2) DEFAULT 0.00,\n"
            "  order_status VARCHAR(50) NOT NULL,\n"
            "  created_at DATETIME NOT NULL,\n"
            "  paid_at DATETIME NULL,\n"
            "  shipped_at DATETIME NULL,\n"
            "  shipping_country VARCHAR(100),\n"
            "  is_deleted TINYINT(1) DEFAULT 0\n"
            ");"
        ),
    },
    "order_items": {
        "table_name": "order_items",
        "description": (
            "Line-item breakdown of individual products contained in each"
            " order. Connects orders to products, tracking item quantities,"
            " unit prices, and line totals."
        ),
        "synonyms": [
            "line items",
            "ordered items",
            "basket items",
            "order details",
            "cart items",
            "units sold",
        ],
        "columns": {
            "order_item_id": "Primary key for the order line item",
            "order_id": "Foreign key referencing orders.order_id",
            "product_id": "Foreign key referencing products.product_id",
            "quantity": "Number of units of this product purchased",
            "unit_price": "Price charged per unit at the time of purchase",
            "line_total": "Subtotal for this line item (quantity multiplied by unit_price)",
        },
        "embedding_text": (
            "Table: order_items. Domain: Order Line Items, Product Sales & Cart"
            " Details. Contains itemized purchase details: which product was"
            " bought in which order, quantity purchased, item price, and line"
            " total. Essential for queries analyzing product quantities per"
            " order or cross-selling."
        ),
        "ddl": (
            "CREATE TABLE order_items (\n"
            "  order_item_id BIGINT PRIMARY KEY,\n"
            "  order_id BIGINT NOT NULL,\n"
            "  product_id BIGINT NOT NULL,\n"
            "  quantity INT NOT NULL,\n"
            "  unit_price DECIMAL(10,2) NOT NULL,\n"
            "  line_total DECIMAL(12,2) NOT NULL\n"
            ");"
        ),
    },
    "products": {
        "table_name": "products",
        "description": (
            "Product catalog, merchandise categories, item names, catalog"
            " pricing, and inventory stock status. Use when querying product"
            " performance, catalog items, or product categories."
        ),
        "synonyms": [
            "merchandise",
            "goods",
            "items",
            "inventory",
            "stock",
            "SKU",
            "categories",
            "catalog",
        ],
        "columns": {
            "product_id": "Primary key uniquely identifying each product",
            "product_name": "Commercial display title / name of the product",
            "category_name": "Category taxonomy (e.g. 'Electronics', 'Clothing', 'Home', 'Software')",
            "unit_price": "Standard catalog list price per unit",
            "inventory_status": "Stock availability: 'in_stock', 'low_stock', 'out_of_stock'",
        },
        "embedding_text": (
            "Table: products. Domain: Products, Catalog, Merchandise &"
            " Inventory. Contains product catalog data, product names, SKU"
            " titles, category_name / product category / department, unit"
            " pricing, and stock availability. Best for questions filtering by"
            " category, top-selling products, or catalog lookup."
        ),
        "ddl": (
            "CREATE TABLE products (\n"
            "  product_id BIGINT PRIMARY KEY,\n"
            "  product_name VARCHAR(255) NOT NULL,\n"
            "  category_name VARCHAR(100) NOT NULL,\n"
            "  unit_price DECIMAL(10,2) NOT NULL,\n"
            "  inventory_status VARCHAR(50) DEFAULT 'in_stock'\n"
            ");"
        ),
    },
    "payments": {
        "table_name": "payments",
        "description": (
            "Payment settlements, cash collection, invoices paid, payment"
            " methods (credit card, bank transfer, PayPal), and settlement"
            " statuses. Used for cash accounting and collected revenue."
        ),
        "synonyms": [
            "cash",
            "settlements",
            "invoices",
            "collected revenue",
            "credit card",
            "wire transfer",
            "receipts",
        ],
        "columns": {
            "payment_id": "Primary key identifying each payment transaction",
            "order_id": "Foreign key referencing orders.order_id",
            "paid_amount": "Actual monetary cash amount received/collected",
            "payment_method": "Channel: 'credit_card', 'wire_transfer', 'paypal', 'stripe'",
            "payment_status": "Settlement state: 'settled', 'pending', 'failed', 'refunded'",
            "payment_date": "Timestamp when funds were collected and settled",
        },
        "embedding_text": (
            "Table: payments. Domain: Payments, Cash Collection & Settlements."
            " Tracks actual collected cash revenue, invoice settlement, payment"
            " gateway methods (credit card, wire, paypal), and transaction"
            " status ('settled'). Best for cash-accounting revenue queries and"
            " payment failure audits."
        ),
        "ddl": (
            "CREATE TABLE payments (\n"
            "  payment_id BIGINT PRIMARY KEY,\n"
            "  order_id BIGINT NOT NULL,\n"
            "  paid_amount DECIMAL(12,2) NOT NULL,\n"
            "  payment_method VARCHAR(50),\n"
            "  payment_status VARCHAR(50) NOT NULL,\n"
            "  payment_date DATETIME\n"
            ");"
        ),
    },
    "audit_logs": {
        "table_name": "audit_logs",
        "description": (
            "Internal system change logs, administrative audits, login history,"
            " and permission tracking. Rarely needed for standard business"
            " analytics."
        ),
        "synonyms": ["logs", "system events", "admin activity", "history"],
        "columns": {
            "log_id": "Primary key identifying the audit record",
            "user_id": "ID of the administrative user who triggered the event",
            "action": "Description of the operation performed",
            "timestamp": "Time the event took place",
        },
        "embedding_text": (
            "Table: audit_logs. Domain: Administrative Audit, System Event"
            " Logs & Security. Tracks administrative record modifications,"
            " logins, and internal operational events."
        ),
        "ddl": (
            "CREATE TABLE audit_logs (\n"
            "  log_id BIGINT PRIMARY KEY,\n"
            "  user_id BIGINT NOT NULL,\n"
            "  action VARCHAR(255) NOT NULL,\n"
            "  timestamp DATETIME NOT NULL\n"
            ");"
        ),
    },
}


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


class SchemaAndValueLinker:

    def __init__(
        self,
        registry_path: Optional[Union[str, Path]] = None,
        mysql_url: Optional[str] = None,
        table_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
        mock_db_values: Optional[Dict[str, List[str]]] = None,
    ):
        self.registry_path = find_registry_file(registry_path)
        with open(self.registry_path, "r") as f:
            self.registry : Dict[str, Any] = yaml.safe_load(f)
        self.mysql_url = mysql_url
        self.table_catalog = table_catalog or DEFAULT_TABLE_CATALOG
        self.mock_db_values = mock_db_values or {
            "company_name": ["Acme Corp NA", "Acme Global Ltd", "Globex Inc", "Initech"],
            "product_category": ["Cloud Software", "Hardware", "Analytics", "Security"],
        }
        self.engine: Optional[Any] = None
        
        if mysql_url:
            self.engine = create_engine(mysql_url, pool_pre_ping=True)

        self.chroma_collection  = None
        client = chromadb.Client()
        self.chroma_collection = client.get_or_create_collection(
            name = "mysql_schema_catalog"
        )
        self._index_table_description()

    def _index_table_description(self):
        if not self.chroma_collection:
            return
        ids = list(self.table_catalog.keys()) # Unique string identifiers for each record
        documents = []  
        metadatas = []
        for tbl, meta in self.table_catalog.items():
            embed_str = meta.get("embedding_text") or meta.get("description", "")
            synonyms_str = ", ".join(meta.get("synonyms", []))
            cols_str = "; ".join(
                f"{col} ({desc})" for col, desc in meta.get("columns", {}).items()
            )
            documents.append(
                f"{embed_str} Synonyms: {synonyms_str}. Columns: {cols_str}."
            )
            metadatas.append({"table_name": tbl})
        self.chroma_collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

 # --------------------------------------------------------------------------
    def retrieve_candidate_tables(self, spec: QuerySpec, top_k: int = 3) -> List[str]:
        """Finds relevant MySQL tables for the terms inside QuerySpec."""
        query_terms: List[str] = (
            list(spec.metrics)
            + list(spec.entities)
            + list(spec.groupings)
            + [f.field_or_dimension for f in spec.filters]
            + [str(f.value) for f in spec.filters]
        )
        search_text = " ".join(query_terms).lower()

        candidate_tables: List[str] = []

        # 1. ChromaDB vector search (Takes 5ms, scales to thousands of tables)
        if self.chroma_collection and search_text.strip():
            results = self.chroma_collection.query(
                query_texts=[search_text],
                n_results=min(top_k, len(self.table_catalog)),
            )
            for tbl_id in results.get("ids", [[]])[0]:
                if tbl_id not in candidate_tables:
                    candidate_tables.append(tbl_id)

        # 2. Check entity_value_lookup tables for active filters (Safety check)
        entity_lookup = self.registry.get("entity_value_lookup", {})
        for f in spec.filters:
            col_key = f.field_or_dimension.lower().strip()
            if col_key in entity_lookup:
                tbl = entity_lookup[col_key].get("table")
                if tbl and tbl not in candidate_tables:
                    candidate_tables.append(tbl)

        # 3. Auto-include bridge table `order_items` if both `orders`/`customers` and `products` are needed
        if "products" in candidate_tables and (
            "orders" in candidate_tables or "customers" in candidate_tables
        ):
            if "orders" not in candidate_tables:
                candidate_tables.append("orders")
            if "order_items" not in candidate_tables:
                candidate_tables.append("order_items")

        return candidate_tables or ["customers", "orders"]
    
    # STEP 2B: CHECK ENTITY FILTER VALUES IN MYSQL (SQLAlchemy or Mock Fallback)
    def verify_filter_values(self, spec: QuerySpec) -> Dict[str, List[str]]:
        """Runs parameterized MySQL LIKE queries for `entity_value_lookup` filters."""
        entity_lookup = self.registry.get("entity_value_lookup", {})
        db_lookup_results: Dict[str, List[str]] = {}
        for f in spec.filters:
            col_key = f.field_or_dimension.lower().strip()
            if col_key not in entity_lookup:
                continue

            rule = entity_lookup[col_key]
            if rule.get("match_strategy") != "mysql_like":
                continue

            search_val = str(f.value).strip()
            matches: List[str] = []

            if self.engine is not None:
                sql_query = rule["lookup_query"]
                with self.engine.connect() as conn:
                    rows = conn.execute(text(sql_query), {"val": search_val}).fetchall()
                    matches = [str(r[0]) for r in rows]
            else:
                known_values = self.mock_db_values.get(col_key, [])
                matches = [
                    v for v in known_values if search_val.lower() in v.lower()
                ]

            if hasattr(f, "db_matches"):
                f.db_matches = matches
            db_lookup_results[col_key] = matches

        return db_lookup_results

    # --------------------------------------------------------------------------
    # STEP 2C: FETCH LINKED SCHEMA DDL & COLUMN COMMENTS FOR NODE 7
    # --------------------------------------------------------------------------
    def get_linked_schema_ddl(self, linked_tables: List[str]) -> str:
        """Returns the CREATE TABLE DDL + column comments for only the candidate tables."""
        ddl_blocks: List[str] = []

        if self.engine is not None and HAS_SQLALCHEMY:
            with self.engine.connect() as conn:
                for tbl in linked_tables:
                    row = conn.execute(text(f"SHOW CREATE TABLE `{tbl}`;")).fetchone()
                    if row and len(row) > 1:
                        ddl_blocks.append(str(row[1]) + ";")
            return "\n\n".join(ddl_blocks)

        for tbl in linked_tables:
            if tbl in self.table_catalog:
                meta = self.table_catalog[tbl]
                ddl_str = meta.get("ddl", "")
                cols = meta.get("columns", {})
                col_comments = "\n".join(
                    f"-- {col}: {desc}" for col, desc in cols.items()
                )
                ddl_blocks.append(f"{col_comments}\n{ddl_str}".strip())
        return "\n\n".join(ddl_blocks)

    # --------------------------------------------------------------------------
    # MAIN ENTRY POINT FOR NODE 2
    # --------------------------------------------------------------------------
    def link(self, spec: QuerySpec) -> Dict[str, Any]:
        linked_tables = self.retrieve_candidate_tables(spec)
        if hasattr(spec, "linked_tables"):
            spec.linked_tables = linked_tables

        db_lookup_results = self.verify_filter_values(spec)
        linked_ddl = self.get_linked_schema_ddl(linked_tables)

        return {
            "query_spec": spec,
            "linked_tables": linked_tables,
            "db_lookup_results": db_lookup_results,
            "linked_schema_ddl": linked_ddl,
        }


def schema_linker_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph Node 2 wrapper."""
    linker = SchemaAndValueLinker(
        registry_path=state.get("registry_path", "sematic_registry.yaml"),
        mysql_url=state.get("mysql_url"),
    )
    return linker.link(state["query_spec"])


if __name__ == "__main__":
    from ambiguity_detector import AmbiguityDetector

    linker = SchemaAndValueLinker("sematic_registry.yaml")
    detector = AmbiguityDetector("sematic_registry.yaml")

    print("=" * 72)
    print("NODE 2 -> NODE 3 PIPELINE TEST (With Rich DEFAULT_TABLE_CATALOG)")
    print("=" * 72)

    spec_from_node_1 = QuerySpec(
        raw_question="Orders for Acme in Cyberware category",
        metrics=["revenue"],
        entities=["orders"],
        filters=[
            FilterCondition(
                field_or_dimension="company_name",
                operator="LIKE",
                value="Acme",
            ),
            FilterCondition(
                field_or_dimension="product_category",
                operator="LIKE",
                value="Cyberware",
            ),
        ],
        time_window="last 30 days",
    )

    node_2_out = linker.link(spec_from_node_1)
    linked_spec = node_2_out["query_spec"]

    print(f"1. Linked Tables (Notice 'audit_logs' is excluded!): {node_2_out['linked_tables']}")
    print(f"2. DB Value Lookup Matches                         : {node_2_out['db_lookup_results']}")
    final_spec = detector.detect(
        spec=linked_spec,
        linked_tables=node_2_out["linked_tables"],
        db_lookup_results=node_2_out["db_lookup_results"],
    )
    print(f"3. Node 3 Ambiguities Caught                       : {len(final_spec.detected_ambiguities)}")
    for idx, amb in enumerate(final_spec.detected_ambiguities, 1):
        d = amb if isinstance(amb, dict) else (amb.model_dump() if hasattr(amb, "model_dump") else amb.dict())
        print(f"   [{idx}] {d['ambiguity_type']} on '{d['trigger_term']}'")