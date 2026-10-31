from typing import Any, Dict, List, Optional, Union
from QuerySpec import AmbiguityFlag, FilterCondition, OrderBySpec, QuerySpec

from langgraph.types import interrupt 



def format_clarification_request(spec: QuerySpec) -> Dict[str, Any]:
    """
    Extracts all detected ambiguities from QuerySpec and formats them into
    a clean, typed payload for a frontend UI (radio buttons, dropdowns, or CLI).
    """
    items = []
    for idx, amb in enumerate(spec.detected_ambiguities, 1):
        # amb can be an AmbiguityFlag object or a dict
        if isinstance(amb, dict):
            amb_type = amb.get("ambiguity_type", "AMBIGUITY")
            trigger = amb.get("trigger_term", "")
            prompt = amb.get("clarification_prompt", "")
            opts = amb.get("options", {})
        else:
            amb_type = amb.ambiguity_type
            trigger = amb.trigger_term
            prompt = amb.clarification_prompt
            opts = amb.options

        items.append({
            "index": idx,
            "ambiguity_type": amb_type,
            "trigger_term": trigger,
            "clarification_prompt": prompt,
            "options": opts,  # {"gross_revenue": "Gross Revenue (before discounts & tax)", ...}
        })

    return {
        "status": "clarification_needed",
        "raw_question": spec.raw_question,
        "total_ambiguities": len(items),
        "clarifications": items,
    }


def interactive_cli_clarify(spec: QuerySpec) -> Dict[str, str]:
    """
    Local CLI helper: displays the clarification prompts in the terminal
    and asks the user to pick an option (1, 2, 3...) interactively.
    Returns: Dict[trigger_term, selected_option_key]
    """
    payload = format_clarification_request(spec)
    user_choices: Dict[str, str] = {}

    print("\n" + "=" * 70)
    print("🤔 CLARIFICATION NEEDED TO GENERATE ACCURATE SQL")
    print(f"Original Question: '{payload['raw_question']}'")
    print("=" * 70)

    for item in payload["clarifications"]:
        trigger = item["trigger_term"]
        prompt = item["clarification_prompt"]
        options = item["options"]

        print(f"\n[{item['index']}/{payload['total_ambiguities']}] {prompt}")
        opt_keys = list(options.keys())

        for idx, key in enumerate(opt_keys, 1):
            label = options[key]
            print(f"   [{idx}] {label}")

        while True:
            try:
                choice_idx = int(input(f"   Select option [1-{len(opt_keys)}]: ").strip())
                if 1 <= choice_idx <= len(opt_keys):
                    selected_key = opt_keys[choice_idx - 1]
                    user_choices[trigger] = selected_key
                    break
                print(f"   ❌ Invalid choice. Please enter a number between 1 and {len(opt_keys)}.")
            except ValueError:
                print(f"   ❌ Please enter a valid number.")

    print("=" * 70)
    print(f"✅ User selections recorded: {user_choices}\n")
    return user_choices


# LANGGRAPH NODE 4 FUNCTION WRAPPER
def clarification_node(state: Dict[str, Any]) -> Dict[str, Any]:
    spec: QuerySpec = state.get("query_spec")
    if not spec:
        raise ValueError("State is missing 'query_spec'")

    # If no ambiguities were detected, pass through directly
    if not spec.detected_ambiguities:
        return {
            **state,
            "clarification_needed": False,
        }

    # 1. Prepare structured payload for the user
    payload = format_clarification_request(spec)
    user_choices: Dict[str, str] = interrupt(payload)

    # Note: QuerySpec.resolved_choices is NOT populated here.
    # Node 6 (Spec Resolver) will inspect state["user_choices"] and resolve it.
    return {
        **state,
        "query_spec": spec,
        "user_choices": user_choices,
        "clarification_needed": False,
    }


# ==============================================================================
# LOCAL TEST RUNNER
# ==============================================================================
if __name__ == "__main__":
    # Mock an ambiguous QuerySpec coming out of Node 3
    ambiguous_spec = QuerySpec(
        raw_question="Show me top premium customers by revenue",
        metrics=["revenue"],
        entities=["customers", "orders"],
        filters=[
            FilterCondition(
                field_or_dimension="customer_tier",
                operator="=",
                value="premium",
                db_matches=None,
            )
        ],
        detected_ambiguities=[
            AmbiguityFlag(
                ambiguity_type="COLUMN_COLLISION",
                trigger_term="revenue",
                clarification_prompt="How would you like to calculate revenue?",
                options={
                    "gross_revenue": "Gross Revenue (before discounts & tax)",
                    "net_revenue": "Net Revenue (after discounts, excluding tax)",
                    "collected_revenue": "Collected Cash (paid invoices only)",
                },
            ),
            AmbiguityFlag(
                ambiguity_type="MULTIPLE_INTERPRETATIONS",
                trigger_term="premium",
                clarification_prompt="The term 'premium' maps to multiple customer tiers in the database. Which tier(s) should I include?",
                options={
                    "Enterprise": "Enterprise",
                    "Mid-Market": "Mid-Market",
                    "both": "Both Enterprise & Mid-Market",
                },
            ),
        ],
    )

    print("=" * 70)
    print("NODE 4 TEST: FORMATTING CLARIFICATION PAYLOAD")
    print("=" * 70)

    # 1. Verify payload formatting
    payload = format_clarification_request(ambiguous_spec)
    import pprint
    pprint.pprint(payload)

    print("\nSimulating user response: {'revenue': 'net_revenue', 'premium': 'Enterprise'}")
    mock_user_response = {"revenue": "net_revenue", "premium": "Enterprise"}

    # 2. Simulate Node 4 state update
    mock_state = {"query_spec": ambiguous_spec}
    ambiguous_spec.resolved_choices.update(mock_user_response)
    print(f"Updated QuerySpec.resolved_choices: {ambiguous_spec.resolved_choices}")

