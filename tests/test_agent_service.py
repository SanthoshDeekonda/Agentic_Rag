from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from agent_service import app

client = TestClient(app)


@pytest.mark.parametrize(
    "payload", [{}, {"question": ""}, {"question": "   "}, {"question": "a" * 2001}]
)
def test_invoke_rejects_invalid_input(payload):
    with patch("agent_service.agent_graph.invoke") as invoke:
        assert client.post("/invoke", json=payload).status_code == 422
    invoke.assert_not_called()


@pytest.mark.parametrize("is_rbi_related", [True, False])
def test_invoke_returns_full_state(is_rbi_related):
    source = "https://example.org/rbi"
    docs = (
        [Document(page_content="Circular excerpt", metadata={"source": source})]
        if is_rbi_related
        else []
    )
    state = {
        "question": "Sample question",
        "is_rbi_related": is_rbi_related,
        "generation": "Sample reply",
        "sources": [source] if is_rbi_related else [],
        "web_search": False,
        "documents": docs,
    }
    with patch("agent_service.agent_graph.invoke", return_value=state) as invoke:
        response = client.post("/invoke", json={"question": "  Sample question  "})
    invoke.assert_called_once_with({"question": "Sample question"})
    assert response.status_code == 200
    assert response.json() == {
        **state,
        "documents": [doc.model_dump(mode="json") for doc in docs],
    }
