import os
from typing import List, Dict, Any, Optional, Union
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

NODE_0_SYSTEM_PROMPT = """You are Node 0 (Conversation Context Loader) in an analytical Text-to-SQL pipeline.

Your ONLY job is to take a conversational user question and prior chat history, and rewrite the question into a completely SELF-CONTAINED, standalone question that can be understood in total isolation without reading past messages.

### RULES:
1. **Resolve Pronouns & References**:
   - Replace words like "them", "it", "those", "that table", "same filter", "now by month" with the concrete entities, metrics, and filters mentioned in earlier turns.
2. **Handle Ellipses & Follow-ups**:
   - If the user asks a partial question like "What about last month?" or "How about in Germany?", merge the previous question's intent with the new constraint.
3. **If Already Standalone**:
   - If the user's question does not depend on chat history, or is already complete and self-contained, return it VERBATIM (do not alter its wording).
4. **DO NOT Answer the Question**:
   - Do NOT execute the query.
   - Do NOT generate SQL code.
   - Output ONLY the rewritten question string—no commentary, no explanations, no quotes.

### FEW-SHOT EXAMPLES:

--- Example 1 (Adding a time window) ---
Chat History:
User: "Show me top 5 customers by revenue"
Assistant: "Here are the top 5 customers by revenue..."
Follow-up: "What about last month?"
Rewritten: Show me top 5 customers by revenue for last month

--- Example 2 (Changing a filter / pronoun resolution) ---
Chat History:
User: "How many orders were placed by Enterprise customers?"
Assistant: "Enterprise customers placed 1,420 orders."
Follow-up: "What about Mid-Market and SMB?"
Rewritten: How many orders were placed by Mid-Market and SMB customers?

--- Example 3 (Adding an extra condition) ---
Chat History:
User: "List total sales for each product category"
Assistant: "Here is the sales breakdown by category..."
Follow-up: "Filter that table for cancelled orders only"
Rewritten: List total sales for each product category for cancelled orders only

--- Example 4 (Already Standalone Question) ---
Chat History:
User: "Show me revenue by region"
Assistant: "Here is revenue by region..."
Follow-up: "How many active employees are in the HR department?"
Rewritten: How many active employees are in the HR department?
"""

NODE_0_PROMPT = ChatPromptTemplate.from_messages([
    ("system", NODE_0_SYSTEM_PROMPT),
    ("human", """Chat History:
{chat_history}

Current Question: {user_question}

Rewritten Standalone Question:""")
])


def format_chat_history(messages: Optional[List[Union[Dict[str, str], Any]]]) -> str:   
    """Formats list of message dicts into readable text for the prompt."""
    if not messages:
        return "None"
    formatted = []
    for msg in messages:   #msg can be a dict or an object with attributes (type , content)
        if isinstance(msg, dict):   # isinstance(msg, dict) checks if msg is a dictionary
            role = msg.get("role", "User").capitalize()
            content = msg.get("content", "")
            formatted.append(f"{role}: {content}")
        elif hasattr(msg, "content"): # hasattr(msg, "content") checks if msg has an attribute named "content"
            if(getattr(msg, "type","") == "ai"):
                roles = "Assistant"
            else:
                roles = "User"
            formatted.append(f"{roles}: {msg.content}")
        else:
            formatted.append(str(msg))
    return "\n".join(formatted) if formatted else "None"


def resolve_conversation_context(
    user_question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    user_question = user_question.strip()

    if not chat_history:   # Fast-path: If there is no chat history, the question is already the first turn
        return user_question

    llm = ChatGroq(model="openai/gpt-oss-20b", temperature=0)

    chain = NODE_0_PROMPT | llm | StrOutputParser() #StrOutputParser automatically unwraps the AIMessage and returns only the raw string

    formatted_history = format_chat_history(chat_history)
    standalone_question = chain.invoke({
        "chat_history": formatted_history,   #It replaces {chat_history} with formatted_history. It replaces {chat_history} with formatted_history.
        "user_question": user_question,       #It replaces {user_question} with user_question.
    })

    return standalone_question.strip()

# LANGGRAPH NODE 0 FUNCTION WRAPPER

def conversation_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    raw_question = state.get("user_question", "")
    history = state.get("chat_history", [])

    standalone = resolve_conversation_context(
        user_question=raw_question,
        chat_history=history,
    )

    return {
        **state,
        "standalone_question": standalone,
    }


# ==============================================================================
# LOCAL CLI VERIFICATION
# ==============================================================================
if __name__ == "__main__":
    test_history = [
        {"role": "user", "content": "Show me top 5 customers by revenue"},
        {"role": "assistant", "content": "Found 5 customers: Acme, Globex, Initech, Umbrella, Hooli."},
    ]
    follow_up = "What about last month?"

    print("=" * 60)
    print("NODE 0: CONVERSATION CONTEXT LOADER TEST")
    print("=" * 60)
    print("Chat History:")
    print(format_chat_history(test_history))
    print(f"\nCurrent User Question: '{follow_up}'")

    try:
        resolved = resolve_conversation_context(follow_up, test_history)
        print(f"\nRewritten Standalone Question:\n-> '{resolved}'")
    except Exception as e:
        print(f"\nExecution skipped or API key needed: {e}")

