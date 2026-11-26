from typing import Annotated

from fastapi import FastAPI
from langchain_core.documents import Document
from pydantic import BaseModel, StringConstraints

from AgenticWorkflow.graph import app as agent_graph


class AgentQuestion(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


class AgentStateResponse(BaseModel):
    question: str
    is_rbi_related: bool
    generation: str
    sources: list[str]
    web_search: bool
    documents: list[Document]


app = FastAPI(title="RBI Agent")


@app.post("/invoke")
def invoke(request: AgentQuestion) -> AgentStateResponse:
    result = agent_graph.invoke({"question": request.question})
    return AgentStateResponse.model_validate(result)
