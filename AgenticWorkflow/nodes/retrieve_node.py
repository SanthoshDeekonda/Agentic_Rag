from typing import Any, Dict

from AgenticWorkflow.state import AgentState
from ingestion import get_vector_retriever


def retrieve_node(state: AgentState) -> Dict[str, Any]:

    question: str = state["question"]

    retrieved_docs = get_vector_retriever().invoke(input=question)

    return {"question": question, "documents": retrieved_docs}
