from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from typing import Any

import chromadb
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


CHROMA_HOST = os.getenv("CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_TENANT = os.getenv("CHROMA_TENANT", "default_tenant")
CHROMA_DATABASE = os.getenv("CHROMA_DATABASE", "default_database")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/embeddings")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nomic-embed-text")
EMBEDDING_MAX_CHARS = int(os.getenv("EMBEDDING_MAX_CHARS", "1200"))
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "12"))


client = chromadb.HttpClient(
    host=CHROMA_HOST,
    port=CHROMA_PORT,
    tenant=CHROMA_TENANT,
    database=CHROMA_DATABASE,
)

app = FastAPI(title="Chroma Portal API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SemanticSearchRequest(BaseModel):
    collection: str
    query: str
    n_results: int = 10


class KeywordSearchRequest(BaseModel):
    collection: str
    keyword: str


class HybridSearchRequest(BaseModel):
    collection: str
    query: str
    n_results: int = 10


class CreateCollectionRequest(BaseModel):
    name: str
    similarity_space: str = Field(default="cosine", pattern="^(cosine|l2|ip)$")
    chunk_strategy_default: str = "semantic"
    remark: str = ""


class RenameCollectionRequest(BaseModel):
    new_name: str
    remark: str | None = None


class ChunkPreviewRequest(BaseModel):
    text: str
    mode: str = Field(default="semantic", pattern="^(semantic|paragraph|sentence|fixed)$")
    chunk_size: int = Field(default=420, ge=80, le=4000)
    overlap: int = Field(default=60, ge=0, le=800)


class IngestRequest(BaseModel):
    text: str
    mode: str = Field(default="semantic", pattern="^(semantic|paragraph|sentence|fixed)$")
    chunk_size: int = Field(default=420, ge=80, le=4000)
    overlap: int = Field(default=60, ge=0, le=800)
    clear_existing: bool = False


class RecordCreateRequest(BaseModel):
    document: str
    metadata: dict[str, Any] | None = None


class RecordUpdateRequest(BaseModel):
    document: str
    metadata: dict[str, Any] | None = None


class BatchDeleteRequest(BaseModel):
    ids: list[str]


def normalize_lines(text: str) -> list[str]:
    normalized = text.replace("\u3000", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in normalized.split("\n")]
    return [line for line in lines if line]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；;.!?])", text)
    return [part.strip() for part in parts if part.strip()]


def split_fixed(text: str, chunk_size: int, overlap: int) -> list[str]:
    source = re.sub(r"\s+", " ", text).strip()
    if not source:
        return []
    step = max(1, chunk_size - overlap)
    chunks = []
    for start in range(0, len(source), step):
        chunk = source[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(source):
            break
    return chunks


def split_paragraph(text: str, chunk_size: int, overlap: int) -> list[str]:
    lines = normalize_lines(text)
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = line
    if current:
        chunks.append(current)

    if overlap > 0 and len(chunks) > 1:
        out: list[str] = []
        for idx, chunk in enumerate(chunks):
            if idx == 0:
                out.append(chunk)
                continue
            tail = chunks[idx - 1][-overlap:]
            out.append(f"{tail}\n{chunk}")
        return out
    return chunks


def split_sentence_mode(text: str, chunk_size: int) -> list[str]:
    sentences = split_sentences(re.sub(r"\s+", " ", text).strip())
    if not sentences:
        return []
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(split_fixed(sentence, chunk_size, overlap=0))
            continue
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def detect_heading(line: str) -> bool:
    if re.match(r"^[一二三四五六七八九十]+、", line):
        return True
    if re.match(r"^[A-D]类卷", line):
        return True
    if line.endswith("评分标准") or line.endswith("注意事项"):
        return True
    return False


def split_semantic(text: str, chunk_size: int) -> list[str]:
    lines = normalize_lines(text)
    if not lines:
        return []

    chunks: list[str] = []
    current_heading = ""
    current_body: list[str] = []

    def flush() -> None:
        nonlocal current_body
        if current_heading or current_body:
            block = (current_heading + "\n" + "\n".join(current_body)).strip()
            if block:
                if len(block) <= chunk_size:
                    chunks.append(block)
                else:
                    chunks.extend(split_sentence_mode(block, chunk_size))
        current_body = []

    for line in lines:
        if detect_heading(line):
            flush()
            current_heading = line
        else:
            current_body.append(line)
    flush()
    return chunks


def chunk_text(text: str, mode: str, chunk_size: int, overlap: int) -> list[str]:
    source = text.strip()
    if not source:
        return []
    if mode == "fixed":
        return split_fixed(source, chunk_size, overlap)
    if mode == "sentence":
        return split_sentence_mode(source, chunk_size)
    if mode == "paragraph":
        return split_paragraph(source, chunk_size, overlap)
    return split_semantic(source, chunk_size)


def embed_query(text: str) -> list[float]:
    safe_text = re.sub(r"\s+", " ", text).strip()
    if EMBEDDING_MAX_CHARS > 0 and len(safe_text) > EMBEDDING_MAX_CHARS:
        safe_text = safe_text[:EMBEDDING_MAX_CHARS]

    resp = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": safe_text},
        timeout=120,
    )
    if not resp.ok:
        raise HTTPException(status_code=500, detail=f"embedding failed: {resp.text}")
    vector = resp.json().get("embedding")
    if not vector:
        raise HTTPException(status_code=500, detail="embedding response missing vector")
    return vector


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    batch_url = OLLAMA_URL.replace("/api/embeddings", "/api/embed")
    normalized = [re.sub(r"\s+", " ", text).strip()[:EMBEDDING_MAX_CHARS] for text in texts]

    try:
        vectors: list[list[float]] = []
        for offset in range(0, len(normalized), EMBED_BATCH_SIZE):
            batch = normalized[offset : offset + EMBED_BATCH_SIZE]
            resp = requests.post(
                batch_url,
                json={"model": OLLAMA_MODEL, "input": batch},
                timeout=300,
            )
            if not resp.ok:
                raise RuntimeError(resp.text)
            payload = resp.json()
            batch_vectors = payload.get("embeddings")
            if not isinstance(batch_vectors, list):
                raise RuntimeError("invalid batch embeddings response")
            vectors.extend(batch_vectors)

        if len(vectors) != len(texts):
            raise RuntimeError("batch embeddings length mismatch")
        return vectors
    except Exception:
        return [embed_query(text) for text in texts]


def get_collection_info(name: str) -> dict[str, Any]:
    collection = client.get_collection(name=name)
    configuration = getattr(collection, "configuration_json", None) or getattr(collection, "configuration", {})
    metadata = collection.metadata or {}
    hnsw = configuration.get("hnsw") or {}
    return {
        "name": collection.name,
        "similaritySpace": hnsw.get("space", "unknown"),
        "embeddingModel": metadata.get("embedding_model", OLLAMA_MODEL),
        "chunkStrategy": metadata.get("chunk_strategy_default", "unknown"),
        "remark": metadata.get("remark", ""),
        "count": collection.count(),
    }


def recreate_collection_with_new_name(old_name: str, new_name: str) -> None:
    old_collection = client.get_collection(name=old_name)
    old_config = getattr(old_collection, "configuration_json", None) or getattr(old_collection, "configuration", {})
    old_hnsw = old_config.get("hnsw") or {"space": "cosine"}
    old_meta = old_collection.metadata or {}

    create_kwargs: dict[str, Any] = {
        "name": new_name,
        "configuration": {"hnsw": {"space": old_hnsw.get("space", "cosine")}},
    }
    if old_meta:
        create_kwargs["metadata"] = old_meta

    new_collection = client.create_collection(**create_kwargs)

    total = old_collection.count()
    page_size = 200
    for offset in range(0, total, page_size):
        batch = old_collection.get(
            limit=page_size,
            offset=offset,
            include=["documents", "metadatas", "embeddings"],
        )
        ids = to_list(batch.get("ids"))
        documents = to_list(batch.get("documents"))
        metadatas = to_list(batch.get("metadatas"))
        embeddings = to_list(batch.get("embeddings"))
        if ids:
            new_collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

    client.delete_collection(name=old_name)


def update_collection_remark(collection_name: str, remark: str) -> None:
    collection = client.get_collection(name=collection_name)
    old_metadata = collection.metadata or {}
    new_metadata = {**old_metadata, "remark": remark}
    collection.modify(metadata=new_metadata)


def normalize_text(value: str) -> str:
    return value.strip().lower()


def lexical_metrics(query: str, doc: str, heading_path: str = "") -> tuple[float, int, float]:
    query_norm = normalize_text(query)
    doc_norm = normalize_text(doc)
    heading_norm = normalize_text(heading_path)

    keyword_hits = doc_norm.count(query_norm) if query_norm else 0
    query_chars = {ch for ch in query_norm if ch.strip()}
    doc_chars = {ch for ch in doc_norm if ch.strip()}
    overlap = (len(query_chars & doc_chars) / len(query_chars)) if query_chars else 0.0
    heading_boost = 0.25 if query_norm and query_norm in heading_norm else 0.0
    lexical_score = min(1.0, keyword_hits * 0.6 + overlap * 0.4 + heading_boost)
    return lexical_score, keyword_hits, overlap


def to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value)


def first_list(value: Any) -> list[Any]:
    outer = to_list(value)
    if not outer:
        return []
    return to_list(outer[0])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/collections")
def list_collections() -> list[dict[str, Any]]:
    result = []
    for item in client.list_collections():
        name = item.name if hasattr(item, "name") else str(item)
        result.append(get_collection_info(name))
    result.sort(key=lambda x: x["name"])
    return result


@app.post("/collections")
def create_collection(payload: CreateCollectionRequest) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="collection name is required")
    try:
        client.create_collection(
            name=name,
            configuration={"hnsw": {"space": payload.similarity_space}},
            metadata={
                "embedding_model": OLLAMA_MODEL,
                "chunk_strategy_default": payload.chunk_strategy_default,
                "remark": payload.remark.strip(),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "collection": get_collection_info(name)}


@app.patch("/collections/{collection_name}")
def rename_collection(collection_name: str, payload: RenameCollectionRequest) -> dict[str, Any]:
    new_name = payload.new_name.strip()
    next_remark = payload.remark.strip() if payload.remark is not None else None
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    if new_name == collection_name:
        if next_remark is not None:
            try:
                update_collection_remark(collection_name, next_remark)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "collection": get_collection_info(collection_name)}

    try:
        recreate_collection_with_new_name(collection_name, new_name)
        if next_remark is not None:
            update_collection_remark(new_name, next_remark)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"success": True, "collection": get_collection_info(new_name)}


@app.delete("/collections/{collection_name}")
def delete_collection(collection_name: str) -> dict[str, Any]:
    try:
        client.delete_collection(name=collection_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True}


@app.post("/chunk/preview")
def chunk_preview(payload: ChunkPreviewRequest) -> dict[str, Any]:
    chunks = chunk_text(payload.text, payload.mode, payload.chunk_size, payload.overlap)
    preview = chunks[:20]
    return {
        "mode": payload.mode,
        "chunkSize": payload.chunk_size,
        "overlap": payload.overlap,
        "count": len(chunks),
        "preview": preview,
    }


@app.post("/collections/{collection_name}/ingest")
def ingest_text(collection_name: str, payload: IngestRequest) -> dict[str, Any]:
    chunks = chunk_text(payload.text, payload.mode, payload.chunk_size, payload.overlap)
    if not chunks:
        raise HTTPException(status_code=400, detail="no chunks generated from input text")

    try:
        if payload.clear_existing:
            old = client.get_collection(name=collection_name)
            config = getattr(old, "configuration_json", None) or getattr(old, "configuration", {})
            hnsw = config.get("hnsw") or {"space": "cosine"}
            client.delete_collection(name=collection_name)
            collection = client.create_collection(
                name=collection_name,
                configuration={"hnsw": {"space": hnsw.get("space", "cosine")}},
                metadata={
                    "embedding_model": OLLAMA_MODEL,
                    "chunk_strategy_default": payload.mode,
                    "recreated_at": datetime.utcnow().isoformat(),
                },
            )
        else:
            collection = client.get_collection(name=collection_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    embeddings = embed_texts(chunks)
    ingest_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    ids = [f"manual-{ingest_id}-{uuid.uuid4().hex[:8]}-{idx:03d}" for idx in range(len(chunks))]
    metadatas = [
        {
            "source": "manual_input",
            "chunk_strategy": payload.mode,
            "chunk_index": idx,
            "ingest_id": ingest_id,
            "embedding_model": OLLAMA_MODEL,
        }
        for idx in range(len(chunks))
    ]

    collection.add(ids=ids, documents=chunks, metadatas=metadatas, embeddings=embeddings)

    return {
        "success": True,
        "collection": collection_name,
        "added": len(chunks),
        "mode": payload.mode,
        "total": collection.count(),
    }


@app.get("/collections/{collection_name}/records")
def get_records(
    collection_name: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    collection = client.get_collection(name=collection_name)
    total = collection.count()
    offset = (page - 1) * page_size
    records = collection.get(limit=page_size, offset=offset, include=["documents", "metadatas", "embeddings"])

    ids = to_list(records.get("ids"))
    docs = to_list(records.get("documents"))
    metas = to_list(records.get("metadatas"))
    embs = to_list(records.get("embeddings"))

    items = []
    for idx, rid in enumerate(ids):
        doc = docs[idx] if idx < len(docs) and docs[idx] is not None else ""
        meta = metas[idx] if idx < len(metas) and metas[idx] is not None else {}
        emb = embs[idx] if idx < len(embs) else None
        items.append(
            {
                "id": rid,
                "document": doc,
                "metadata": meta,
                "embeddingDimension": len(emb) if emb is not None else 0,
            }
        )

    return {"total": total, "page": page, "pageSize": page_size, "records": items}


@app.post("/collections/{collection_name}/records")
def create_record(collection_name: str, payload: RecordCreateRequest) -> dict[str, Any]:
    document = payload.document.strip()
    if not document:
        raise HTTPException(status_code=400, detail="document is required")

    collection = client.get_collection(name=collection_name)
    embedding = embed_query(document)
    record_id = f"manual-single-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    metadata = payload.metadata or {}
    metadata = {
        **metadata,
        "source": metadata.get("source", "manual_single"),
        "embedding_model": OLLAMA_MODEL,
        "updated_at": datetime.utcnow().isoformat(),
    }

    collection.add(ids=[record_id], documents=[document], metadatas=[metadata], embeddings=[embedding])
    return {"success": True, "id": record_id}


@app.patch("/collections/{collection_name}/records/{record_id}")
def update_record(collection_name: str, record_id: str, payload: RecordUpdateRequest) -> dict[str, Any]:
    document = payload.document.strip()
    if not document:
        raise HTTPException(status_code=400, detail="document is required")

    collection = client.get_collection(name=collection_name)
    current = collection.get(ids=[record_id], include=["metadatas", "documents"])
    ids = to_list(current.get("ids"))
    if not ids:
        raise HTTPException(status_code=404, detail="record not found")

    current_meta_list = to_list(current.get("metadatas"))
    current_meta = current_meta_list[0] if current_meta_list else {}
    current_meta = current_meta or {}
    next_meta = {**current_meta, **(payload.metadata or {})}
    next_meta["updated_at"] = datetime.utcnow().isoformat()
    next_meta["embedding_model"] = OLLAMA_MODEL

    embedding = embed_query(document)
    collection.update(ids=[record_id], documents=[document], metadatas=[next_meta], embeddings=[embedding])
    return {"success": True}


@app.delete("/collections/{collection_name}/records/{record_id}")
def delete_record(collection_name: str, record_id: str) -> dict[str, Any]:
    collection = client.get_collection(name=collection_name)
    collection.delete(ids=[record_id])
    return {"success": True}


@app.post("/collections/{collection_name}/records/batch-delete")
def batch_delete_records(collection_name: str, payload: BatchDeleteRequest) -> dict[str, Any]:
    ids = [rid for rid in payload.ids if rid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="ids are required")

    collection = client.get_collection(name=collection_name)
    collection.delete(ids=ids)
    return {"success": True, "deleted": len(ids)}


@app.post("/search/keyword")
def keyword_search(payload: KeywordSearchRequest) -> dict[str, Any]:
    keyword = payload.keyword.strip().lower()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword is required")

    collection = client.get_collection(name=payload.collection)
    all_records = collection.get(include=["documents", "metadatas", "embeddings"])
    ids = to_list(all_records.get("ids"))
    docs = to_list(all_records.get("documents"))
    metas = to_list(all_records.get("metadatas"))
    embs = to_list(all_records.get("embeddings"))

    results = []
    for idx, rid in enumerate(ids):
        doc = docs[idx] if idx < len(docs) and docs[idx] is not None else ""
        if keyword in doc.lower():
            meta = metas[idx] if idx < len(metas) and metas[idx] is not None else {}
            emb = embs[idx] if idx < len(embs) else None
            results.append(
                {
                    "id": rid,
                    "document": doc,
                    "metadata": meta,
                    "embeddingDimension": len(emb) if emb is not None else 0,
                }
            )
    return {"mode": "keyword", "query": payload.keyword, "records": results}


@app.post("/search/semantic")
def semantic_search(payload: SemanticSearchRequest) -> dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    embedding = embed_query(query)
    collection = client.get_collection(name=payload.collection)
    res = collection.query(
        query_embeddings=[embedding],
        n_results=payload.n_results,
        include=["documents", "metadatas", "distances"],
    )

    ids = first_list(res.get("ids"))
    docs = first_list(res.get("documents"))
    metas = first_list(res.get("metadatas"))
    dists = first_list(res.get("distances"))
    items = []
    for idx, rid in enumerate(ids):
        doc = docs[idx] if idx < len(docs) and docs[idx] is not None else ""
        meta = metas[idx] if idx < len(metas) and metas[idx] is not None else {}
        dist = float(dists[idx]) if idx < len(dists) and dists[idx] is not None else None
        items.append(
            {
                "id": rid,
                "document": doc,
                "metadata": meta,
                "distance": dist,
                "embeddingDimension": len(embedding),
            }
        )

    return {"mode": "semantic", "query": payload.query, "embeddingModel": OLLAMA_MODEL, "records": items}


@app.post("/search/hybrid")
def hybrid_search(payload: HybridSearchRequest) -> dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    embedding = embed_query(query)
    collection = client.get_collection(name=payload.collection)
    semantic_pool_size = max(30, min(200, payload.n_results * 8))

    semantic = collection.query(
        query_embeddings=[embedding],
        n_results=semantic_pool_size,
        include=["documents", "metadatas", "distances"],
    )

    all_records = collection.get(include=["documents", "metadatas"])
    all_ids = to_list(all_records.get("ids"))
    all_docs = to_list(all_records.get("documents"))
    all_metas = to_list(all_records.get("metadatas"))

    sem_ids = first_list(semantic.get("ids"))
    sem_docs = first_list(semantic.get("documents"))
    sem_metas = first_list(semantic.get("metadatas"))
    sem_dists = first_list(semantic.get("distances"))

    is_short_query = len(query) <= 4
    weight_semantic = 0.25 if is_short_query else 0.62
    weight_lexical = 1.0 - weight_semantic

    merged: dict[str, dict[str, Any]] = {}
    for idx, rid in enumerate(sem_ids):
        doc = sem_docs[idx] if idx < len(sem_docs) and sem_docs[idx] is not None else ""
        meta = sem_metas[idx] if idx < len(sem_metas) and sem_metas[idx] is not None else {}
        distance = float(sem_dists[idx]) if idx < len(sem_dists) and sem_dists[idx] is not None else 1.0
        semantic_score = max(0.0, 1.0 - distance)
        heading = str(meta.get("heading_path", ""))
        lexical_score, keyword_hits, overlap = lexical_metrics(query, doc, heading)
        hybrid_score = semantic_score * weight_semantic + lexical_score * weight_lexical
        if is_short_query and keyword_hits == 0:
            hybrid_score -= 0.08

        merged[rid] = {
            "id": rid,
            "document": doc,
            "metadata": meta,
            "distance": distance,
            "semanticScore": round(semantic_score, 6),
            "lexicalScore": round(lexical_score, 6),
            "keywordHits": keyword_hits,
            "charOverlap": round(overlap, 6),
            "score": round(hybrid_score, 6),
        }

    for idx, rid in enumerate(all_ids):
        doc = all_docs[idx] if idx < len(all_docs) and all_docs[idx] is not None else ""
        meta = all_metas[idx] if idx < len(all_metas) and all_metas[idx] is not None else {}
        heading = str(meta.get("heading_path", ""))
        lexical_score, keyword_hits, overlap = lexical_metrics(query, doc, heading)
        if lexical_score <= 0:
            continue

        existing = merged.get(rid)
        if existing:
            semantic_score = existing["semanticScore"]
            hybrid_score = semantic_score * weight_semantic + lexical_score * weight_lexical
            if is_short_query and keyword_hits == 0:
                hybrid_score -= 0.08
            existing["lexicalScore"] = max(existing["lexicalScore"], round(lexical_score, 6))
            existing["keywordHits"] = max(existing["keywordHits"], keyword_hits)
            existing["charOverlap"] = max(existing["charOverlap"], round(overlap, 6))
            existing["score"] = round(max(existing["score"], hybrid_score), 6)
        else:
            hybrid_score = lexical_score * weight_lexical
            merged[rid] = {
                "id": rid,
                "document": doc,
                "metadata": meta,
                "distance": None,
                "semanticScore": 0.0,
                "lexicalScore": round(lexical_score, 6),
                "keywordHits": keyword_hits,
                "charOverlap": round(overlap, 6),
                "score": round(hybrid_score, 6),
            }

    sorted_items = sorted(
        merged.values(),
        key=lambda x: (x["score"], x["keywordHits"], x["semanticScore"]),
        reverse=True,
    )

    top_items = sorted_items[: payload.n_results]
    for item in top_items:
        item["embeddingDimension"] = len(embedding)

    return {
        "mode": "hybrid",
        "query": payload.query,
        "embeddingModel": OLLAMA_MODEL,
        "weights": {"semantic": weight_semantic, "lexical": weight_lexical},
        "records": top_items,
    }
