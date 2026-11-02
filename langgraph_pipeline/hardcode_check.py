from ambiguity_detector import AmbiguityDetector, _to_dict, FilterCondition, OrderBySpec, QuerySpec, AmbiguityFlag

if __name__ == "__main__":
    detector = AmbiguityDetector("sematic_registry.yaml")

    print("=" * 72)
    print("TEST 1: AMBIGUOUS QUERY ('Show me top premium customers by revenue')")
    print("=" * 72)
    spec_1 = QuerySpec(
        raw_question="Show me top premium customers by revenue",
        metrics=["revenue"],
        entities=["customers", "orders"],
        filters=[
            FilterCondition(
                field_or_dimension="customer_tier",
                operator="=",
                value="premium",
            )
        ],
        time_window=None,
        order_by=OrderBySpec(field_or_metric="revenue", direction="DESC", limit=5),
    )
    checked_1 = detector.detect(spec_1, linked_tables=["customers", "orders"])
    print(f"Ambiguities Found: {len(checked_1.detected_ambiguities)}")
    for idx, item in enumerate(checked_1.detected_ambiguities, 1):
        amb = _to_dict(item)
        print(f"  [{idx}] {amb['ambiguity_type']} on '{amb['trigger_term']}'")
        print(f"      Prompt : {amb['clarification_prompt']}")
        print(f"      Options: {amb['options']}")

    print("\n" + "=" * 72)
    print("TEST 2: CLEAN QUERY ('Top 5 Enterprise customers by gross revenue')")
    print("=" * 72)
    spec_2 = QuerySpec(
        raw_question="Top 5 Enterprise customers by gross revenue",
        metrics=["orders.gross_amount"],
        entities=["customers", "orders"],
        filters=[
            FilterCondition(
                field_or_dimension="customer_tier",
                operator="=",
                value="Enterprise",
            )
        ],
        time_window="2026-09-01 to 2026-09-30",
        resolved_choices={"revenue": "gross_revenue"},
    )
    checked_2 = detector.detect(spec_2, linked_tables=["customers", "orders"])
    print(f"Ambiguities Found: {len(checked_2.detected_ambiguities)}")
    print(
        f"Route Decision   : {'Node 5 (Pass-through)' if len(checked_2.detected_ambiguities) == 0 else 'Node 4 (Interrupt)'}"
    )

    print("\n" + "=" * 72)
    print("TEST 3: ENTITY LOOKUP COLLISION & VALUE NOT FOUND")
    print("=" * 72)
    spec_3 = QuerySpec(
        raw_question="Show orders for Acme and Cyberware",
        metrics=["orders.order_id"],
        entities=["customers", "orders", "products"],
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
    checked_3 = detector.detect(
        spec_3,
        linked_tables=["customers", "orders", "products"],
        db_lookup_results={
            "company_name": ["Acme Corp NA", "Acme Global Ltd"],
            "product_category": [],
        },
    )
    print(f"Ambiguities Found: {len(checked_3.detected_ambiguities)}")
    for idx, item in enumerate(checked_3.detected_ambiguities, 1):
        amb = _to_dict(item)
        print(f"  [{idx}] {amb['ambiguity_type']} on '{amb['trigger_term']}'")
        print(f"      Prompt : {amb['clarification_prompt']}")
        print(f"      Options: {amb['options']}")
    