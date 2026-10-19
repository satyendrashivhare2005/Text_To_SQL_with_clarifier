from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any , Union
import yaml 
from QuerySpec import FilterCondition, OrderBySpec, QuerySpec, AmbiguityFlag

def _to_dict(item: Any) -> Dict[str, Any]:
    """Compatible serializer for both Pydantic v1 (.dict) and v2 (.model_dump)."""
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    return dict(item)

class AmbiguityDetector:   
    def __init__(self, registry_path: Union[str, Path] = "sematic_registry.yaml"):
        self.registry_path = Path(registry_path)
        if(not Path(self.registry_path).exists()):
            raise FileNotFoundError(f"Registry file not found at {self.registry_path}")
        else:
            self.registry = self._load_registry()
            # print(self.registry.keys())

    def _load_registry(self) -> Dict[str, Any]:
        with open(self.registry_path, 'r') as file:
            return yaml.safe_load(file)

  
    def detect(
        self,
        spec: QuerySpec,
        linked_tables: Optional[List[str]] = None,
        db_lookup_results: Optional[Dict[str, List[str]]] = None,
    ) -> QuerySpec:
        ambiguities: List[AmbiguityFlag] = []
        assumptions: List[str] = []

        active_tables: List[str] = (
            linked_tables
            or getattr(spec, "linked_tables", None)
            or [e.lower().strip() for e in spec.entities]
        )
        db_lookup_results = db_lookup_results or {}

        # Gather all terms referenced in metrics, groupings, and order_by
        search_terms = [m.lower().strip() for m in spec.metrics] + [
            g.lower().strip() for g in spec.groupings]
        if spec.order_by and spec.order_by.field_or_metric:
            order_term = spec.order_by.field_or_metric.lower().strip()
            if order_term not in search_terms:
                search_terms.append(order_term)
        
        # 1. Check COLUMN_COLLISION (e.g., "revenue", "order_date", "location")
        for rule_key, rule in self.registry.get("column_collision", {}).items():
            synonyms = [s.lower() for s in rule.get("synonyms", [])]
            matched_terms = [t for t in search_terms if t in synonyms]


            if matched_terms and rule_key not in spec.resolved_choices:
                options_dict = {
                    opt_key: opt_val["label"]
                    for opt_key, opt_val in rule.get("options", {}).items()
                }
                ambiguities.append(AmbiguityFlag(
                    ambiguity_type="column_collisions",
                    trigger_term = matched_terms[0],
                    clarification_prompt=rule.get("clarification_prompt", "Please clarify the term."),
                    options=options_dict
                ))


        #2. Check UNDEFINED_METRIC (e.g., "active", "top", "churned")
        filter_values = [f.value.lower().strip() for f in spec.filters]
        all_items = filter_values + search_terms
        for rule_key, rule in self.registry.get("undefined_metric", {}).items():
            synonyms = [s.lower() for s in rule.get("synonyms", [])]
            matched_terms = [t for t in all_items if t in synonyms]

            if matched_terms and rule_key not in spec.resolved_choices:
                options_dict = {
                    opt_key: opt_val["label"]
                    for opt_key, opt_val in rule.get("options", {}).items()
                }
                ambiguities.append(AmbiguityFlag(
                    ambiguity_type="undefined_metric",
                    trigger_term=matched_terms[0],
                    clarification_prompt=rule.get("clarification_prompt", "Please clarify the term."),
                    options=options_dict
                ))


        missing_rules = self.registry.get("missing_filter_rules", {}) #Check MISSING_FILTER (large tables without date range or vague time)

        #3a. Vague time phrase check ("recently", "this period")
        vague_time = missing_rules.get("vague_time_phrases", {})

              # 3a. Vague time phrase check ("recently", "this period")
        vague_time = missing_rules.get("vague_time_phrases", {})

        if spec.time_window and vague_time:
            time_window_lower = spec.time_window.lower().strip()
            triggers = [t.lower() for t in vague_time.get("triggers", [])]

            # If the user used a vague phrase and hasn't resolved it yet
            if time_window_lower in triggers and "time_window" not in spec.resolved_choices:
                options_dict = {
                    opt_key: opt_val["label"]
                    for opt_key, opt_val in vague_time.get("options", {}).items()
                }
                
                # Format the prompt with the exact word the user used
                prompt_template = vague_time.get(
                    "clarification_prompt", 
                    "What exact timeframe do you mean by '{trigger_word}'?"
                )
                clarification = prompt_template.format(trigger_word=spec.time_window)

                ambiguities.append(
                    AmbiguityFlag(
                        ambiguity_type=vague_time.get("ambiguity_type", "MISSING_FILTER"),
                        trigger_term=spec.time_window,
                        clarification_prompt=clarification,
                        options=options_dict,
                    )
                )



        # 3b. Large table queried with no time_window
        large_tables = missing_rules.get("large_tables_requiring_date_filter", {})
        for table_name, table_rule in large_tables.items():
            if (
                table_name in active_tables
                and not spec.time_window
                and f"{table_name}_date_filter" not in spec.resolved_choices
            ):
                options_dict = {
                    k: v["label"]
                    for k, v in table_rule.get("suggested_options", {}).items()
                }
                ambiguities.append(
                    AmbiguityFlag(
                        ambiguity_type="MISSING_FILTER",
                        trigger_term=table_name,
                        clarification_prompt=table_rule["clarification_prompt"],
                        options=options_dict,
                    )
                )
        # 4. Check VALUE_NOT_FOUND & MULTIPLE_INTERPRETATIONS on Filters
        entity_lookup = self.registry.get("entity_value_lookup", {})
        for f in spec.filters:
            col_key = f.field_or_dimension.lower().strip()
            if col_key in entity_lookup and col_key not in spec.resolved_choices:
                lookup_rule = entity_lookup[col_key]
                val_str = str(f.value).strip()
                strategy = lookup_rule.get("match_strategy")

                # Strategy A: Exact Enum + Synonym Map
                if strategy == "exact_enum":
                    allowed = lookup_rule.get("allowed_values", [])
                    synonyms = lookup_rule.get("synonym_map", {})

                    if val_str in allowed:
                        continue
                    elif val_str.lower() in synonyms:
                        mapped_vals = synonyms[val_str.lower()]
                        if len(mapped_vals) > 1:
                            mult_rule = lookup_rule["on_multiple_matches"]
                            ambiguities.append(
                                AmbiguityFlag(
                                    ambiguity_type=mult_rule["ambiguity_type"],
                                    trigger_term=val_str,
                                    clarification_prompt=mult_rule[
                                        "clarification_prompt"
                                    ].format(user_value=val_str),
                                    options={v: v for v in mapped_vals},
                                )
                            )
                    else:
                        zero_rule = lookup_rule["on_zero_matches"]
                        ambiguities.append(
                            AmbiguityFlag(
                                ambiguity_type=zero_rule["ambiguity_type"],
                                trigger_term=val_str,
                                clarification_prompt=zero_rule[
                                    "clarification_prompt"
                                ].format(user_value=val_str),
                                options={v: v for v in allowed},
                            )
                        )

                # Strategy B: MySQL LIKE Lookup Matches (from f.db_matches or db_lookup_results)
                elif strategy == "mysql_like":
                    matches = getattr(f, "db_matches", None)
                    if matches is None and col_key in db_lookup_results:
                        matches = db_lookup_results[col_key]

                    if matches is not None:
                        if len(matches) == 0:
                            zero_rule = lookup_rule["on_zero_matches"]
                            ambiguities.append(
                                AmbiguityFlag(
                                    ambiguity_type=zero_rule["ambiguity_type"],
                                    trigger_term=val_str,
                                    clarification_prompt=zero_rule[
                                        "clarification_prompt"
                                    ].format(user_value=val_str),
                                    options={},
                                )
                            )
                        elif len(matches) > 1:
                            mult_rule = lookup_rule["on_multiple_matches"]
                            ambiguities.append(
                                AmbiguityFlag(
                                    ambiguity_type=mult_rule["ambiguity_type"],
                                    trigger_term=val_str,
                                    clarification_prompt=mult_rule[
                                        "clarification_prompt"
                                    ].format(
                                        user_value=val_str,
                                        matched_db_values=", ".join(matches),
                                    ),
                                    options={
                                        v: f"Include {v}" for v in matches
                                    },
                                )
                            )

            #5 for the active tables, check if there are any global filters that should be applied and add them to assumptions
        global_filters = self.registry.get("safe_defaults", {}).get(
            "global_table_filters", {}
        )
        for tbl in active_tables:
            if tbl in global_filters:
                assumptions.append(global_filters[tbl]["explanation"])

        # Store results back on QuerySpec (compatible with both Dict and AmbiguityFlag lists)
        try:
            spec.detected_ambiguities = ambiguities
        except Exception:
            spec.detected_ambiguities = [_to_dict(a) for a in ambiguities]

        if hasattr(spec, "assumptions_made"):
            spec.assumptions_made = assumptions
        if hasattr(spec, "confidence_score"):
            spec.confidence_score = 1.0 if len(ambiguities) == 0 else 0.25

        return spec
def run_ambiguity_detector(
    spec: QuerySpec,
    registry_path: Union[str, Path] = "semantic_registry.yaml",
    linked_tables: Optional[List[str]] = None,
    db_lookup_results: Optional[Dict[str, List[str]]] = None,
) -> QuerySpec:
    """Convenience function to run Node 3 on a QuerySpec."""
    detector = AmbiguityDetector(registry_path=registry_path)
    return detector.detect(
        spec=spec,
        linked_tables=linked_tables,
        db_lookup_results=db_lookup_results,
    )


def ambiguity_detector_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph Node 3 wrapper.
    Expects `state["query_spec"]` and optional `state["linked_tables"]`.
    """
    detector = AmbiguityDetector(
        registry_path=state.get("registry_path", "semantic_registry.yaml")
    )
    updated_spec = detector.detect(
        spec=state["query_spec"],
        linked_tables=state.get("linked_tables"),
        db_lookup_results=state.get("db_lookup_results"),
    )
    is_confident = len(updated_spec.detected_ambiguities) == 0
    return {
        "query_spec": updated_spec,
        "is_confident": is_confident,
        "next_node": "pass_through" if is_confident else "clarification_node",
    }






            
    





