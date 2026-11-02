from typing import Annotated, Any, Dict, List, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict
from QuerySpec import QuerySpec
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# 1. State definition for the entire 12-node pipeline
class AgentState(TypedDict):
    # Context & Conversational input (Node 0)
    user_question: str
    standalone_question: str
    chat_history: Annotated[List[BaseMessage], add_messages]

    # Semantic Query Specification (Node 1)
    query_spec: QuerySpec

    # Schema & Value Linking (Node 2)
    linked_tables: List[str]
    linked_schema_ddl: str
    db_lookup_results: Dict[str, List[str]]

    # Ambiguity Detection & Clarification (Nodes 3, 4, 5, 6)
    is_confident: bool
    clarification_needed: bool
    user_choices: Dict[str, str]

    # SQL Generation, Guardrails & Execution (Nodes 7, 8, 9, 10)
    raw_sql: str
    sql_error: Optional[str]
    retry_count: int
    query_results: Optional[List[Dict[str, Any]]]

    # Final Presentation & Response (Node 11)
    final_response: str
    next_node: Optional[str]


# 2. Import all 12 nodes and routers
from contextlaoder_Node_0 import conversation_context_node  # Node 0
from Node_1 import intent_extractor_node  # Node 1
from Node_2 import schema_linker_node  # Node 2
from ambiguity_detector import ambiguity_detector_node  # Node 3
from Node_4 import clarification_node  # Node 4
from Node_5 import pass_through_node, route_after_ambiguity_detector  # Node 5
from Node_6 import spec_resolver_node  # Node 6
from Node_7 import sql_generator_node  # Node 7
from Node_8 import sql_validator_node, route_after_sql_validator  # Node 8
from Node_9 import query_safety_gate_node, route_after_safety_gate  # Node 9
from Node_10 import safe_execution_node, route_after_execution  # Node 10
from Node_11 import result_formatter_node  # Node 11

# 3. Initialize StateGraph
workflow = StateGraph(AgentState)

# 4. Register all 12 nodes
workflow.add_node("context_loader", conversation_context_node)  # Node 0
workflow.add_node("intent_extractor", intent_extractor_node)  # Node 1
workflow.add_node("schema_linker", schema_linker_node)  # Node 2
workflow.add_node("ambiguity_detector", ambiguity_detector_node)  # Node 3
workflow.add_node("clarification_node", clarification_node)  # Node 4
workflow.add_node("pass_through_node", pass_through_node)  # Node 5
workflow.add_node("spec_resolver", spec_resolver_node)  # Node 6
workflow.add_node("sql_generator", sql_generator_node)  # Node 7
workflow.add_node("sql_validator", sql_validator_node)  # Node 8
workflow.add_node("query_safety_gate", query_safety_gate_node)  # Node 9
workflow.add_node("safe_execution", safe_execution_node)  # Node 10
workflow.add_node("final_presentation", result_formatter_node)  # Node 11

# 5. Connect Linear Edges: Nodes 0 -> 1 -> 2 -> 3
workflow.add_edge(START, "context_loader")
workflow.add_edge("context_loader", "intent_extractor")
workflow.add_edge("intent_extractor", "schema_linker")
workflow.add_edge("schema_linker", "ambiguity_detector")

# 6. Branching after Node 3 (Ambiguity Detector)
workflow.add_conditional_edges(
    "ambiguity_detector",
    route_after_ambiguity_detector,
    {
        "clarification_node": "clarification_node",
        "pass_through_node": "pass_through_node",
    },
)

# 7. Clarification Path: Node 4 -> Node 6 -> Node 7
workflow.add_edge("clarification_node", "spec_resolver")
workflow.add_edge("spec_resolver", "sql_generator")

# 8. Fast Path: Node 5 -> Node 7
workflow.add_edge("pass_through_node", "sql_generator")

# 9. SQL Generation to AST Validation: Node 7 -> Node 8
workflow.add_edge("sql_generator", "sql_validator")

# 10. Branching after Node 8 (AST Validator self-correction loop)
workflow.add_conditional_edges(
    "sql_validator",
    route_after_sql_validator,
    {
        "query_safety_gate": "query_safety_gate",
        "sql_generator": "sql_generator",
        "final_presentation": "final_presentation",
    },
)

# 11. Branching after Node 9 (Cost Guardrail self-correction loop)
workflow.add_conditional_edges(
    "query_safety_gate",
    route_after_safety_gate,
    {
        "safe_execution": "safe_execution",
        "sql_generator": "sql_generator",
        "final_presentation": "final_presentation",
    },
)

# 12. Branching after Node 10 (Runtime DB error self-correction loop)
workflow.add_conditional_edges(
    "safe_execution",
    route_after_execution,
    {
        "final_presentation": "final_presentation",
        "sql_generator": "sql_generator",
    },
)

# 13. Terminal Edge: Node 11 -> END
workflow.add_edge("final_presentation", END)

# 14. Compile graph with MemorySaver checkpointer
app = workflow.compile(checkpointer=MemorySaver())


# Visual test runner
if __name__ == "__main__":
    try:
        png_bytes = app.get_graph().draw_mermaid_png()
        output_file = "pipeline_graph.png"
        with open(output_file, "wb") as f:
            f.write(png_bytes)
        print(f"✅ Success! Full 12-Node pipeline graph image saved to: {output_file}")
    except Exception as e:
        print(f"❌ Could not render PNG directly: {e}")
        print("\nMermaid Architecture Code:")
        print(app.get_graph().draw_mermaid())
