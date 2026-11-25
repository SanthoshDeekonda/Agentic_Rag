from pathlib import Path

from langchain_core.documents import Document


DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCE_HEADER = "Text source URL: "


def load_rbi_documents(data_dir: Path = DATA_DIR) -> list[Document]:
    documents = []
    for path in sorted(data_dir.glob("*.txt")):
        content = path.read_text(encoding="utf-8")
        header = content.partition("\n\n")[0]
        source = next(
            (
                line.removeprefix(SOURCE_HEADER).strip()
                for line in header.splitlines()
                if line.startswith(SOURCE_HEADER)
            ),
            "",
        )
        if not source.startswith(("https://", "http://")):
            raise ValueError(f"Missing or invalid text source URL in {path}")

        documents.append(Document(page_content=content, metadata={"source": source}))

    return documents


rbi_docs = load_rbi_documents()

print(rbi_docs)
