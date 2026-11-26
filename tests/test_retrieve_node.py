from AgenticWorkflow.chains.retrieval_grader_chain import (
    GradeDocuments,
    retrieval_grader,
)
from AgenticWorkflow.nodes.retrieve_node import retrieve_node

# def test_retrieve_node():
#     res = retrieve_node({"question":"Who is a Resident?"})

#     for i in res["documents"]:
#         print(f"\nSource: {i.metadata['source']}\n")
#         print(f"\ncontent: {i.page_content}\n")

#     # assert len(res['documents']) == 5


def test_retrieve_grader_chain():
    # question = "RBI press release"
    question = "what is the price of the car"
    res = retrieve_node({"question": question})

    context = res["documents"][0].page_content

    grade: GradeDocuments = retrieval_grader.invoke(
        input={"question": question, "document": context}
    )

    # assert grade.binary_score == "yes"
    assert grade.binary_score == "no"
