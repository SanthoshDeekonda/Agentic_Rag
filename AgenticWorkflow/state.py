from typing import List, NotRequired, TypedDict

from langchain_core.documents import Document


class AgentState(TypedDict):
    """
     Represents the state of the currnet flow

    Attributes:
        question: question
        is_rbi_related: whether the question is in scope
        generation: LLM generation
        sources: URLs cited in the generated response
        web_search: whether to add search
        documents: list of documents
    """

    question: str
    is_rbi_related: NotRequired[bool]
    generation: str
    sources: NotRequired[list[str]]
    web_search: bool
    documents: List[Document]
