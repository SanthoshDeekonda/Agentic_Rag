from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

from langchain_core.documents import Document
from langchain_tavily import TavilySearch

from AgenticWorkflow.state import AgentState


def web_search(state: AgentState) -> Dict[str, Any]:
    question = state["question"]

    web_results = TavilySearch(max_results=3).invoke({"query": question})["results"]
    web_docs = [
        Document(page_content=result["content"], metadata={"source": result["url"]})
        for result in web_results
    ]
    return {"documents": state.get("documents", []) + web_docs, "question": question}
