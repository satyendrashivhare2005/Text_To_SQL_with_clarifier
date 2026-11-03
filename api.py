import json
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langgraph.types import Command
from langgraph_pipeline import app
from fastapi import FastAPI

# 1. Initialize FastAPI application
api = FastAPI(
    title="Ambiguity-Aware Text-to-SQL API",
    description="Enterprise Text-to-SQL engine with LangGraph Human-In-The-Loop clarification.",
    version="1.0.0",
)

# 2. Enable CORS for frontend clients (Streamlit on port 8501, React on 3000/5173)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 3. Request schemas
class QueryRequest(BaseModel):
    question: str = Field(
        ...,
        description="Natural language user question",
        example="Show me top 5 enterprise customers by revenue",
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Unique session ID. If omitted, a new one will be generated.",
    )


class ClarifyRequest(BaseModel):
    thread_id: str = Field(
        ...,
        description="Session thread ID of the paused execution.",
        example="sess_abc123",
    )
    choices: Dict[str, str] = Field(
        ...,
        description="Key-value mapping of trigger term to chosen option.",
        example={"revenue": "net_revenue", "customer_tier": "Enterprise"},
    )


# 4. Helper to extract status (interrupted vs completed) from LangGraph state
def format_graph_output(thread_id: str) -> Dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    state = app.get_state(config)

    # Check if Node 4 paused on interrupt()
    if state.tasks and any(task.interrupts for task in state.tasks):
        interrupt_payload = state.tasks[0].interrupts[0].value
        return {
            "status": "clarification_needed",
            "thread_id": thread_id,
            "clarification": interrupt_payload,
        }

    # Graph reached completion (Node 11)
    raw_response = state.values.get("final_response")
    if isinstance(raw_response, str):
        try:
            parsed_data = json.loads(raw_response)
        except Exception:
            parsed_data = {"summary": raw_response}
    elif isinstance(raw_response, dict):
        parsed_data = raw_response
    else:
        parsed_data = {"summary": "Execution finished."}

    return {
        "status": "completed",
        "thread_id": thread_id,
        "result": parsed_data,
        "sql": state.values.get("raw_sql"),
    }


# 5. Health Check Endpoint
@api.get("/", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": "Ambiguity-Aware Text-to-SQL API",
        "version": "1.0.0",
    }


# 6. Main Query Endpoint: Starts new or multi-turn execution
@api.post("/api/query", tags=["Text-to-SQL"])
def execute_query(req: QueryRequest):
    # Assign or reuse session thread_id
    thread_id = req.thread_id or f"sess_{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        # Start graph execution from START (Node 0)
        app.invoke({"user_question": req.question}, config=config)
        return format_graph_output(thread_id)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution error: {str(e)}",
        )


# 7. Clarification Endpoint: Resumes execution after user selects choices
@api.post("/api/clarify", tags=["Text-to-SQL"])
def submit_clarification(req: ClarifyRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    state = app.get_state(config)

    # Validate that the session exists
    if not state.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread '{req.thread_id}' not found or session has expired.",
        )

    # Validate that the graph is currently awaiting clarification
    if not state.tasks or not any(task.interrupts for task in state.tasks):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Thread '{req.thread_id}' is not currently awaiting clarification.",
        )

    try:
        # Resume the paused graph with user choices
        app.invoke(Command(resume=req.choices), config=config)
        return format_graph_output(req.thread_id)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error resuming pipeline: {str(e)}",
        )


# 8. State Inspection Endpoint: Inspect active thread state
@api.get("/api/state/{thread_id}", tags=["Diagnostics"])
def get_thread_state(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    state = app.get_state(config)

    if not state.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread '{thread_id}' not found.",
        )

    return {
        "thread_id": thread_id,
        "next_nodes": state.next,
        "is_interrupted": bool(state.tasks and any(t.interrupts for t in state.tasks)),
        "current_sql": state.values.get("raw_sql"),
        "retry_count": state.values.get("retry_count", 0),
    }


# 9. Local server runner
if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Starting Text-to-SQL FastAPI server on http://localhost:8000")
    print("📖 Swagger UI Documentation: http://localhost:8000/docs\n")
    uvicorn.run("api:api", host="0.0.0.0", port=8000, reload=True)
