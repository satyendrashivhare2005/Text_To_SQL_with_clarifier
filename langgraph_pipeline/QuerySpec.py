from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class FilterCondition(BaseModel):
    field_or_dimension: str
    operator: str = "="
    value: Any
    # Populated by Node 2 (DB Lookup) before reaching Node 3:
    db_matches: Optional[List[str]] = None


class OrderBySpec(BaseModel):
    field_or_metric: str
    direction: str = "DESC"
    limit: Optional[int] = None

class AmbiguityFlag(BaseModel):
    """Represents a detected ambiguity in the query specification."""

    ambiguity_type: str  # column_collison | undefined_metric | missing filter | value not found
    trigger_term: str
    clarification_prompt: str
    options: Dict[str, str] = Field(default_factory=dict)


class QuerySpec(BaseModel):
    """Represents a structured query specification parsed from a natural-language question."""
    raw_question: str
    metrics: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    filters: List[FilterCondition] = Field(default_factory=list)
    time_window: Optional[str] = None
    groupings: List[str] = Field(default_factory=list)
    order_by: Optional[OrderBySpec] = None

    # Populated by Node 2 (Schema Linker)
    linked_tables: List[str] = Field(default_factory=list)
    linked_columns: List[str] = Field(default_factory=list)
    # Populated by Node 3 (Deterministic Ambiguity Detector)
    detected_ambiguities: List[AmbiguityFlag] = Field(default_factory=list)
    assumptions_made: List[str] = Field(default_factory=list)
    confidence_score: float = 1.0

    # Populated by Node 6 (Spec Resolver after LangGraph interrupt resumes)
    resolved_choices: Dict[str, str] = Field(default_factory=dict)