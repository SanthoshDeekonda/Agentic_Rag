from langgraph.graph import END, StateGraph

if __name__ == "__main__" and not __package__:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from AgenticWorkflow.consts import (
    CHECK_QUESTION_SCOPE,
    GENERATE,
    GRADE_DOCUMENTS,
    RETRIEVE,
    WEBSEARCH,
)
from AgenticWorkflow.nodes import (
    check_question_scope,
    generate,
    grade_docs,
    retrieve_node,
    web_search,
)
from AgenticWorkflow.state import AgentState


def route_question(state: AgentState):
    return RETRIEVE if state["is_rbi_related"] else END


def decide_to_generate(state: AgentState):
    return WEBSEARCH if state["web_search"] else GENERATE


agent_flow = StateGraph(AgentState)

agent_flow.add_node(CHECK_QUESTION_SCOPE, check_question_scope)
agent_flow.add_node(RETRIEVE, retrieve_node)
agent_flow.add_node(GRADE_DOCUMENTS, grade_docs)
agent_flow.add_node(WEBSEARCH, web_search)
agent_flow.add_node(GENERATE, generate)

agent_flow.set_entry_point(CHECK_QUESTION_SCOPE)
agent_flow.add_conditional_edges(CHECK_QUESTION_SCOPE, route_question, [RETRIEVE, END])

agent_flow.add_edge(RETRIEVE, GRADE_DOCUMENTS)

agent_flow.add_conditional_edges(
    GRADE_DOCUMENTS, decide_to_generate, {WEBSEARCH: WEBSEARCH, GENERATE: GENERATE}
)

agent_flow.add_edge(WEBSEARCH, GENERATE)

agent_flow.add_edge(GENERATE, END)

app = agent_flow.compile()

if __name__ == "__main__":
    app.get_graph().draw_mermaid_png(output_file_path="agent_workflow.png")
