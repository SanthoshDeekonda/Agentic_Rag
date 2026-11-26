from typing import Any, Dict

from AgenticWorkflow.chains.retrieval_grader_chain import (
    GradeDocuments,
    retrieval_grader,
)
from AgenticWorkflow.state import AgentState


def grade_docs(state: AgentState) -> Dict[str, Any]:
    """
    Determines whether the retrieved documents are relevant to the question
    If any document is not relevant, we will set a flag to run web search

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): Filtered out irrelevant documents and updated web_search state
    """

    question: str = state["question"]
    retrieved_docs = state["documents"]

    filtered_docs = []

    web_search = False

    for doc in retrieved_docs:
        score: GradeDocuments = retrieval_grader.invoke(
            input={"question": question, "document": doc.page_content}
        )

        grade: str = score.binary_score

        if grade.lower() == "yes":
            filtered_docs.append(doc)
        else:
            web_search = True
            continue

    return {"question": question, "documents": filtered_docs, "web_search": web_search}
