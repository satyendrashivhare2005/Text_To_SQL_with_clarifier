import os
import uuid
import pandas as pd
import requests
import streamlit as st

# 1. Page Configuration & Theme
st.set_page_config(
    page_title="Text-to-SQL Clarifier",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. FastAPI Backend URL
API_URL = os.getenv("API_URL", "http://localhost:8000")

# 3. Initialize Session State
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"sess_{uuid.uuid4().hex[:8]}"

if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_clarification" not in st.session_state:
    st.session_state.pending_clarification = None


# 4. Helper to render formatted response card
def render_response_payload(result_data: dict, sql: str = None):
    # Summary line
    summary = result_data.get("summary", "")
    if summary:
        st.markdown(f"**{summary}**")

    # Display applied clarifications if any
    clarifications = result_data.get("applied_clarifications", {})
    assumptions = result_data.get("assumptions", [])
    if clarifications or assumptions:
        with st.container():
            st.caption("⚙️ **Applied Business Rules & Definitions:**")
            for term, choice in clarifications.items():
                st.info(f"• **{term}**: Resolved to `{choice}`", icon="✅")
            for item in assumptions:
                st.caption(f"• {item}")

    # Display records table
    rows = result_data.get("data", [])
    if rows and isinstance(rows, list):
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Download CSV option
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Data as CSV",
            data=csv,
            file_name=f"query_result_{uuid.uuid4().hex[:6]}.csv",
            mime="text/csv",
        )

    # Display generated SQL in collapsible accordion
    sql_to_show = sql or result_data.get("sql")
    if sql_to_show:
        with st.expander("🔍 View Generated MySQL 8.0 Query", expanded=False):
            st.code(sql_to_show, language="sql")


# 5. Sidebar: Diagnostics & Controls
with st.sidebar:
    st.title("🤖 Text-to-SQL Engine")
    st.caption("Human-In-The-Loop Clarification Architecture")

    # Check backend API status
    try:
        health_resp = requests.get(f"{API_URL}/", timeout=2)
        if health_resp.status_code == 200:
            st.success("🟢 Backend API: Online", icon="✅")
        else:
            st.warning("🟡 Backend API: Unexpected Status")
    except Exception:
        st.error("🔴 Backend API: Offline\nRun `python api.py` to start.")

    st.divider()

    # Session Management
    st.subheader("Session Details")
    st.code(f"Session ID: {st.session_state.thread_id}", language="text")
    if st.button("🔄 New Conversation", use_container_width=True):
        st.session_state.thread_id = f"sess_{uuid.uuid4().hex[:8]}"
        st.session_state.messages = []
        st.session_state.pending_clarification = None
        st.rerun()

    st.divider()

    # Quick Example Prompts
    st.subheader("💡 Example Queries")
    example_prompts = [
        "Show me top 5 enterprise customers by revenue",
        "How many completed orders in last 30 days?",
        "Show all customers with active subscriptions",
    ]
    for prompt in example_prompts:
        if st.button(prompt, use_container_width=True):
            st.session_state.example_to_submit = prompt
            st.rerun()


# 6. Main Chat Header
st.title("💬 Ambiguity-Aware Text-to-SQL")
st.markdown(
    "Ask queries in plain English. If any metric or filter is ambiguous, "
    "the engine will pause and request your exact definition before generating MySQL."
)
st.divider()

# 7. Render Chat History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.write(msg["content"])
        else:
            if "result" in msg:
                render_response_payload(msg["result"], msg.get("sql"))
            else:
                st.write(msg.get("content", ""))


# 8. Interactive Clarification Modal (When Node 4 Interrupted)
if st.session_state.pending_clarification:
    clarification_info = st.session_state.pending_clarification
    clarifications_list = clarification_info.get("clarifications", [])

    with st.chat_message("assistant"):
        st.warning(
            "🤔 **Clarification Needed Before Generating SQL**\n"
            "Your question has multiple business definitions. Please choose your preferences below:",
            icon="⚠️",
        )

        with st.form("clarification_form"):
            selected_choices = {}

            for item in clarifications_list:
                trigger = item.get("trigger_term", "")
                prompt = item.get("clarification_prompt", f"Select definition for '{trigger}':")
                options = item.get("options", {})

                # Format radio button options: value -> human description
                opt_keys = list(options.keys())
                opt_labels = [f"{options[k]} ({k})" for k in opt_keys]
                label_to_key = dict(zip(opt_labels, opt_keys))

                st.markdown(f"**{prompt}**")
                chosen_label = st.radio(
                    label=f"Options for {trigger}",
                    options=opt_labels,
                    key=f"radio_{trigger}",
                    label_visibility="collapsed",
                )
                selected_choices[trigger] = label_to_key[chosen_label]

            # Form submit button
            submit_clarification = st.form_submit_button("Confirm & Generate Query 🚀", use_container_width=True)

            if submit_clarification:
                with st.spinner("Applying choices and running MySQL query..."):
                    try:
                        res = requests.post(
                            f"{API_URL}/api/clarify",
                            json={
                                "thread_id": st.session_state.thread_id,
                                "choices": selected_choices,
                            },
                            timeout=60,
                        )
                        if res.status_code == 200:
                            data = res.json()
                            st.session_state.pending_clarification = None
                            st.session_state.messages.append({
                                "role": "assistant",
                                "result": data.get("result", {}),
                                "sql": data.get("sql"),
                            })
                            st.rerun()
                        else:
                            st.error(f"Error resuming pipeline: {res.text}")
                    except Exception as err:
                        st.error(f"Failed to connect to backend: {err}")


# 9. Handle User Chat Input
user_query = st.chat_input("Ask a question about sales, customers, or revenue...")

# Check if an example prompt was clicked from sidebar
if hasattr(st.session_state, "example_to_submit") and st.session_state.example_to_submit:
    user_query = st.session_state.example_to_submit
    st.session_state.example_to_submit = None

if user_query:
    # Append and display user message
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.write(user_query)

    # Send query to FastAPI backend
    with st.chat_message("assistant"):
        with st.spinner("Analyzing intent and checking schema..."):
            try:
                response = requests.post(
                    f"{API_URL}/api/query",
                    json={
                        "question": user_query,
                        "thread_id": st.session_state.thread_id,
                    },
                    timeout=60,
                )

                if response.status_code == 200:
                    payload = response.json()
                    status_type = payload.get("status")

                    # Scenario A: Ambiguity Detected -> Pause for Clarification
                    if status_type == "clarification_needed":
                        st.session_state.pending_clarification = payload.get("clarification", {})
                        st.rerun()

                    # Scenario B: Fast-Path / Complete
                    elif status_type == "completed":
                        result_data = payload.get("result", {})
                        sql_used = payload.get("sql")
                        st.session_state.messages.append({
                            "role": "assistant",
                            "result": result_data,
                            "sql": sql_used,
                        })
                        render_response_payload(result_data, sql_used)

                    else:
                        st.error(f"Unexpected status: {payload}")

                else:
                    st.error(f"API Error ({response.status_code}): {response.text}")

            except requests.exceptions.ConnectionError:
                st.error("❌ Could not connect to FastAPI server at http://localhost:8000.\nPlease ensure `python api.py` is running.")
            except Exception as e:
                st.error(f"Execution failed: {str(e)}")

