from typing import Any

from AgenticWorkflow.chains.question_scope_chain import question_scope_classifier
from AgenticWorkflow.state import AgentState


def check_question_scope(state: AgentState) -> dict[str, Any]:
    question = state["question"].strip()
    scope = question_scope_classifier.invoke({"question": question})
    if scope.is_rbi_related:
        return {"is_rbi_related": True}
    return {
        "is_rbi_related": False,
        "generation": scope.out_of_scope_response.strip(),
        "sources": [],
        "web_search": False,
        "documents": [],
    }
