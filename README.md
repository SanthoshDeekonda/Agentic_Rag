# RBI regulatory corpus

Run the downloader from this UV project to collect English-language publications from the Reserve Bank of India. The Legal Framework collection also uses official India Code and Ministry of Finance copies for documents listed by RBI.

```sh
uv run --locked python download_rbi.py
```

The default window is the previous three years in India time. Specify dates to reproduce the initial backfill.

```sh
uv run --locked python download_rbi.py --since 2023-11-25 --until 2026-11-25
```

Install Poppler's `pdftotext` for PDF conversion. For scanned pages, also install Poppler's `pdftoppm`, Tesseract, and its English language data. On Debian or Ubuntu these tools are provided by `poppler-utils`, `tesseract-ocr`, and `tesseract-ocr-eng`.

The downloader saves publication text and source metadata in `data/*.txt`. Use `data/manifest.jsonl` for document identifiers, source links, checksums, and extraction status. Use `data/download_report.json` for archive coverage, press release exclusions, and gaps from the latest run. Feed only the text files to the retriever. The report can distinguish a full extraction from a usable body with a missing annexure or a source that failed entirely.

The corpus includes RBI's Legal Framework, Master Directions, standing guidance, public FAQs, and recent notifications, circulars, and regulatory or consumer-facing press releases. Archived documents can be amended, withdrawn, or superseded. Source dates, revision dates, and withdrawal information help the retriever cite the applicable RBI publication. Rerun the downloader to refresh the corpus and preserve the latest usable text when a source becomes unavailable.

Use `--retry-incomplete` with the same date window to retry failed or partial downloads while reusing completed files.

## Run the local agent API

Start Ollama with the existing `qwen3:8b` and `qwen3-embedding:4b` models available and set `TAVILY_API_KEY` in the agent's local `.env` if using web fallback. Run the service from the root of this worktree so it can open the local `.chroma/` index. If the index is missing, run the downloader and then `uv run --locked python ingestion.py` first.

```sh
uv sync --locked
uv run --locked uvicorn agent_service:app --host 127.0.0.1 --port 8001
```

Send `POST /invoke` a JSON object with a `question` field. The service returns the complete workflow state. The Django chat on the `backend` branch uses this endpoint locally.
