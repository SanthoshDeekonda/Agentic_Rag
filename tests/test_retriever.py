from ingestion import get_vector_retriever


def test_retriever():
    retriever = get_vector_retriever()

    res = retriever.invoke(
        "What are the assets out of/ from which funds may be remitted and by whom? Answer"
    )

    for i in res:
        print(
            f"\nsource: {i.metadata["source"]}\n=====\n content: {i.page_content}\n\n"
        )
