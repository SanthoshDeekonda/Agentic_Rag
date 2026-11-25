from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingestion import DATA_DIR, load_rbi_documents


def test_chunks(docs: list[Document] = load_rbi_documents(DATA_DIR)):
    configurations = [
        (1500, 250),
        (2000, 300),
        (2500, 400),
        (3000, 500),
        (4000, 500),
    ]

    for size, overlap in configurations:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=size,
            chunk_overlap=overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""],
        )

        chunks = splitter.split_documents(docs)

        print(
            f"Size: {size} | " f"Overlap: {overlap} | " f"Total chunks: {len(chunks)}"
        )
