from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml
from QuerySpec import AmbiguityFlag, FilterCondition, OrderBySpec, QuerySpec

# NODE 6: SPEC RESOLVER (STATE MERGER)
# Merges the user's clarification choices (from Node 4 interrupt/resume)
# into QuerySpec, locks in exact SQL expressions, adds required tables/filters,
# clears resolved ambiguity flags, and prepares the spec for Node 7 (SQL Generator).

class SpecResolver:
    def __init__(self , registry_path: Union[str, Path] = "sematic_registry.yaml"):
        self.registry_path = Path(registry_path)
        with open(self.registry_path, "r", encoding="utf-8") as f:
            self.registry: Dict[str, Any] = yaml.safe_load(f) or {}

    def resolve(self, spec: QuerySpec, user_choices: Dict[str, Any]) -> QuerySpec:
        if not user_choices:
            return spec  # No user choices to resolve
        spec.resolved_choices.update(user_choices)

        for trigger, choice in user_choices.items():
            self._apply_choice(spec , trigger , choice)

        spec.detected_ambiguities = [
            amb
            for amb in spec.detected_ambiguities
            if amb.trigger_term not in user_choices
        ]
      # 4. If all cleared, restore confidence to 1.0
        if len(spec.detected_ambiguities) == 0:
            spec.confidence_score = 1.0
            
                

        return spec

    
    def _apply_choice(self, spec: QuerySpec, trigger: str, choice: str) -> None:
        trigger_lower = trigger.lower()
        choice_lower = choice.lower()

        collisions = self.registry.get("column_collisions", {})
        for col_name , rule in collisions.items():
            synoyms = [s.lower() for s in rule.get("synonyms", [])]
            if trigger_lower == col_name.lower() or trigger_lower in synoyms:
                opt  = rule.get("options",{}).get(choice_lower)
                if opt:
                    for table in opt.get("required_tables",[]):
                        spec.linked_tables.append(table)
                    if "extra_filter" in opt and "=" in opt["extra_filter"]:
                        k, v = opt["extra_filter"].split("=", 1)
                        spec.filters.append(
                            FilterCondition(
                                field_or_dimension=k.strip(),
                                operator="=",
                                value=v.strip().strip("'\""),
                            )
                        )
                    spec.assumptions_made.append(
                    f"Resolved '{trigger}' using {opt.get('label', choice)}."
                    )
                    return

    
        for f in spec.filters:
            if str(f.value) == trigger:
                f.value = choice
                spec.assumptions_made.append(f"Resolved filter '{f.field_or_dimension}' using user choice '{choice}'")
                return

def spec_resolver_node(state: Dict[str, Any]) -> Dict[str, Any]:
    spec: QuerySpec = state.get("query_spec")
    user_choices: Dict[str, str] = state.get("user_choices", {})
    resolver = SpecResolver()
    resolved_spec = resolver.resolve(spec=spec, user_choices=user_choices)
    return {
        **state,
        "query_spec": resolved_spec,
        "is_confident": len(resolved_spec.detected_ambiguities) == 0,
        "next_node": "sql_generator_node",
    }

    