from typing import Any, Dict, List

from langchain_core.documents import Document

from AgenticWorkflow.chains.generation_chain import generator
from AgenticWorkflow.state import AgentState


def generate(state: AgentState) -> Dict[str, Any]:
    question: str = state["question"]
    docs: List[Document] = state["documents"]

    context = "\n\n".join(
        f"Source: {doc.metadata.get('source', 'Unavailable')}\n{doc.page_content}"
        for doc in docs
    )
    answer = generator.invoke(input={"question": question, "context": context})
    supplied_sources = {
        source
        for doc in docs
        if isinstance(source := doc.metadata.get("source"), str)
        and source.startswith(("https://", "http://"))
    }
    sources = [
        source for source in dict.fromkeys(answer.sources) if source in supplied_sources
    ]

    return {"generation": answer.response, "sources": sources}
