from typing import Any, Dict
from QuerySpec import QuerySpec   # pass through node needs to access QuerySpec for validation and logging

def pass_through_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph Node 5: Pass-Through Node.

    Executes when Node 3 determines the QuerySpec is 100% unambiguous.
    - Sets fast-path flags in state.
    - Ensures confidence_score is logged as 1.0.
    - Transitions straight to Node 7 (SQL Generator) with zero user wait.
    """
    spec: QuerySpec = state.get("query_spec")
    if not spec:
        raise ValueError("State is missing 'query_spec'")

    # Safety check: Ensure no unresolved ambiguities slipped through
    if spec.detected_ambiguities and len(spec.detected_ambiguities) > 0:
        raise ValueError(
            f"Pass-through reached with {len(spec.detected_ambiguities)} unresolved ambiguities!"
        )

    # Log/record the pass-through decision for telemetry & evaluation metrics
    assumptions = list(spec.assumptions_made)
    assumptions.append("Zero ambiguities detected: fast-path taken directly to SQL generation.")

    if hasattr(spec, "assumptions_made"):
        spec.assumptions_made = assumptions
    if hasattr(spec, "confidence_score"):
        spec.confidence_score = 1.0

    return {
        **state,
        "query_spec": spec,
        "clarification_needed": False,
        "is_confident": True,
        "route_taken": "pass_through_fast_path",
        "next_node": "sql_generator_node",
    }

# CONDITIONAL ROUTER (Between Node 3 and Node 4 / Node 5)
def route_after_ambiguity_detector(state: Dict[str, Any]) -> str:
    """
    Evaluates state after Node 3 (Ambiguity Detector).
    - If ambiguities exist or confidence < 0.9 -> Routes to Node 4 (clarification_node).
    - If unambiguous and confidence >= 0.9    -> Routes to Node 5 (pass_through_node).
    """
    spec: QuerySpec = state.get("query_spec")
    if not spec:
        return "clarification_node"

    has_ambiguities = len(spec.detected_ambiguities) > 0
    is_low_confidence = getattr(spec, "confidence_score", 1.0) < 0.9

    if has_ambiguities or is_low_confidence:
        return "clarification_node"   # Node 4 (LangGraph interrupt)
    
    return "pass_through_node"        # Node 5 (Fast Path -> Node 7)


# ==============================================================================
# LOCAL CLI VERIFICATION
# ==============================================================================
if __name__ == "__main__":
    from QuerySpec import FilterCondition, OrderBySpec

    print("=" * 70)
    print("NODE 5: PASS-THROUGH (FAST PATH) VERIFICATION")
    print("=" * 70)

    # Test Case 1: Unambiguous Query ("Top 5 Enterprise customers by gross revenue in Sept 2026")
    clean_spec = QuerySpec(
        raw_question="Top 5 Enterprise customers by gross revenue in Sept 2026",
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
        order_by=OrderBySpec(field_or_metric="orders.gross_amount", direction="DESC", limit=5),
        confidence_score=1.0,
        detected_ambiguities=[],
    )

    clean_state = {"query_spec": clean_spec}
    decision = route_after_ambiguity_detector(clean_state)
    print(f"\n1. Router Decision for Clean Query: '{decision}'")
    assert decision == "pass_through_node", "Clean query should route to pass_through_node"

    updated_state = pass_through_node(clean_state)
    print(f"   Route Taken : {updated_state['route_taken']}")
    print(f"   Is Confident: {updated_state['is_confident']}")
    print(f"   Next Node   : {updated_state['next_node']}")
    print(f"   Confidence  : {updated_state['query_spec'].confidence_score}")

    # Test Case 2: Ambiguous Query (contains detected ambiguities)
    from QuerySpec import AmbiguityFlag
    ambiguous_spec = QuerySpec(
        raw_question="Show revenue",
        metrics=["revenue"],
        entities=["orders"],
        confidence_score=0.25,
        detected_ambiguities=[
            AmbiguityFlag(
                ambiguity_type="COLUMN_COLLISION",
                trigger_term="revenue",
                clarification_prompt="Gross or Net?",
                options={"gross": "Gross", "net": "Net"},
            )
        ],
    )
    ambiguous_state = {"query_spec": ambiguous_spec}
    decision_ambiguous = route_after_ambiguity_detector(ambiguous_state)
    print(f"\n2. Router Decision for Ambiguous Query: '{decision_ambiguous}'")
    assert decision_ambiguous == "clarification_node", "Ambiguous query should route to clarification_node"

    print("\n✅ All Node 5 routing and pass-through tests passed successfully!")

