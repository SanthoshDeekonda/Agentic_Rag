from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document

from AgenticWorkflow.chains.generation_chain import RBIAnswer
from AgenticWorkflow.chains.question_scope_chain import QuestionScope
from AgenticWorkflow.chains.retrieval_grader_chain import GradeDocuments
from AgenticWorkflow.graph import app


@pytest.mark.parametrize(
    ("question", "model_reply"),
    [
        ("What is agent memory?", "I cover RBI topics. Have a question about RBI?"),
        ("", "Please enter a question about the Reserve Bank of India."),
    ],
)
def test_unrelated_question_ends_before_retrieval(question, model_reply):
    with (
        patch(
            "AgenticWorkflow.nodes.check_question_scope.question_scope_classifier"
        ) as classifier,
        patch("AgenticWorkflow.nodes.retrieve_node.get_vector_retriever") as retriever,
    ):
        classifier.invoke.return_value = QuestionScope(
            is_rbi_related=False, out_of_scope_response=model_reply
        )
        result = app.invoke({"question": question})

    classifier.invoke.assert_called_once_with({"question": question})
    retriever.assert_not_called()
    assert result["is_rbi_related"] is False
    assert result["generation"] == model_reply
    assert result["sources"] == []


@pytest.mark.parametrize("score", ["yes", "no"])
def test_rbi_question_reaches_generation_with_source(score):
    question = "What are the remittance rules in India?"
    rbi_source = "https://example.org/rbi-circular"
    web_source = "https://example.org/web-result"
    source, excerpt = (
        (rbi_source, "RBI circular excerpt")
        if score == "yes"
        else (web_source, "Web excerpt")
    )
    retriever = Mock()
    retriever.invoke.return_value = [
        Document(page_content="RBI circular excerpt", metadata={"source": rbi_source})
    ]
    with (
        patch(
            "AgenticWorkflow.nodes.check_question_scope.question_scope_classifier"
        ) as classifier,
        patch(
            "AgenticWorkflow.nodes.retrieve_node.get_vector_retriever",
            return_value=retriever,
        ),
        patch("AgenticWorkflow.nodes.grade_docs.retrieval_grader") as grader,
        patch("AgenticWorkflow.nodes.web_search.TavilySearch") as search,
        patch("AgenticWorkflow.nodes.generate.generator") as generator,
    ):
        classifier.invoke.return_value = QuestionScope(
            is_rbi_related=True, out_of_scope_response=""
        )
        grader.invoke.return_value = GradeDocuments(binary_score=score)
        search.return_value.invoke.return_value = {
            "results": [{"url": web_source, "content": "Web excerpt"}]
        }
        generator.invoke.return_value = RBIAnswer(
            response="Sourced answer",
            sources=[source, "https://example.org/unknown", source],
        )
        result = app.invoke({"question": question})

    retriever.invoke.assert_called_once_with(input=question)
    generator.invoke.assert_called_once_with(
        input={"question": question, "context": f"Source: {source}\n{excerpt}"}
    )
    assert search.called == (score == "no")
    assert result["is_rbi_related"] is True
    assert result["generation"] == "Sourced answer"
    assert result["sources"] == [source]
