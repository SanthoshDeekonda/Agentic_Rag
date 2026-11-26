from hashlib import sha256
from itertools import batched
from pathlib import Path

from chromadb import PersistentClient
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCE_HEADER = "Text source URL: "
VECTOR_COLLECTION_NAME = "RBI_VECTOR_STORE"
DATABASE_PATH = str(DATA_DIR.parent / ".chroma")
EMBEDDING_BATCH_SIZE = 32

Embeddings = OllamaEmbeddings(model="qwen3-embedding:4b")


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


def split_data(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2500,
        chunk_overlap=400,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )

    return splitter.split_documents(documents=docs)


def chunk_id(source: str, text: str) -> str:
    digest = sha256(f"{source}\n{text}".encode("utf-8")).hexdigest()
    return f"rbi-{digest}"


def index_documents(chunks: list[Document], database_path: str = DATABASE_PATH) -> None:
    client = PersistentClient(path=database_path)
    collection = client.get_or_create_collection(
        name=VECTOR_COLLECTION_NAME, embedding_function=None
    )
    existing_ids = set(collection.get(include=[])["ids"])
    legacy_ids = [id_ for id_ in existing_ids if not id_.startswith("rbi-")]
    max_write_batch = client.get_max_batch_size()

    for ids in batched(legacy_ids, max_write_batch):
        existing = collection.get(ids=list(ids), include=["documents", "metadatas"])
        for text, metadata in zip(existing["documents"], existing["metadatas"]):
            if (
                text is not None
                and metadata
                and isinstance(metadata.get("source"), str)
            ):
                existing_ids.add(chunk_id(metadata["source"], text))

    pending_by_text: dict[str, dict[str, dict]] = {}
    for chunk in chunks:
        id_ = chunk_id(chunk.metadata["source"], chunk.page_content)
        if id_ not in existing_ids:
            pending_by_text.setdefault(chunk.page_content, {})[id_] = chunk.metadata

    total = sum(len(rows) for rows in pending_by_text.values())
    if not total:
        print("No new chunks to index.", flush=True)
        return

    print(
        f"Indexing {total:,} chunks from {len(pending_by_text):,} distinct texts.",
        flush=True,
    )
    indexed = 0
    for batch_number, texts in enumerate(
        batched(pending_by_text, EMBEDDING_BATCH_SIZE), 1
    ):
        vectors = Embeddings.embed_documents(list(texts))
        rows = (
            (id_, text, metadata, vector)
            for text, vector in zip(texts, vectors, strict=True)
            for id_, metadata in pending_by_text[text].items()
        )
        for batch in batched(rows, max_write_batch):
            ids, documents, metadatas, embeddings = map(list, zip(*batch))
            collection.upsert(
                ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings
            )
            indexed += len(ids)

        if batch_number == 1 or batch_number % 10 == 0 or indexed == total:
            print(f"Indexed {indexed:,}/{total:,} chunks.", flush=True)


def get_vector_retriever():
    return Chroma(
        collection_name=VECTOR_COLLECTION_NAME,
        persist_directory=DATABASE_PATH,
        embedding_function=Embeddings,
    ).as_retriever(search_kwargs={"k": 5})


if __name__ == "__main__":
    rbi_docs = load_rbi_documents()
    docs_splits = split_data(rbi_docs)
    index_documents(docs_splits)

    retriever = get_vector_retriever()

    res = retriever.invoke("What is meant by Remittance of Assets?")

    print(type(res))
