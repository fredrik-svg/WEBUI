import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import numpy as np


@dataclass
class RAGResult:
    doc_id: str
    chunk_index: int
    text: str
    score: float


class RAGStore:
    """Very small in-process vector store backed by Ollama embeddings."""

    def __init__(self, ollama_host: str, embed_model: str, storage_path: str) -> None:
        self.ollama_host = ollama_host.rstrip("/")
        self.embed_model = embed_model
        self.storage_path = storage_path
        self.documents: List[Dict[str, Any]] = []
        self._chunk_refs: List[Dict[str, Any]] = []
        self._chunk_matrix: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self._lock = asyncio.Lock()
        self._load()
        self._rebuild_index()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.storage_path:
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                docs = data.get("documents") if isinstance(data, dict) else None
                if isinstance(docs, list):
                    self.documents = docs
        except FileNotFoundError:
            self.documents = []
        except json.JSONDecodeError:
            # Corrupt file – ignore but keep empty store
            self.documents = []
        except OSError:
            self.documents = []

    def _save(self) -> None:
        if not self.storage_path:
            return
        directory = os.path.dirname(self.storage_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{self.storage_path}.tmp"
        payload = {"documents": self.documents, "updated_at": datetime.utcnow().isoformat()}
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.storage_path)

    def _rebuild_index(self) -> None:
        refs: List[Dict[str, Any]] = []
        vectors: List[np.ndarray] = []
        for doc in self.documents:
            doc_id = doc.get("id")
            chunks = doc.get("chunks") or []
            for chunk in chunks:
                vec = chunk.get("embedding")
                text = chunk.get("text", "")
                if not isinstance(vec, list) or not vec:
                    continue
                try:
                    arr = np.asarray(vec, dtype=np.float32)
                except (ValueError, TypeError):
                    continue
                norm = np.linalg.norm(arr)
                if norm == 0:
                    continue
                vectors.append(arr / norm)
                refs.append({
                    "doc_id": doc_id,
                    "chunk_index": int(chunk.get("index", 0)),
                    "text": text,
                })
        if vectors:
            self._chunk_matrix = np.vstack(vectors)
        else:
            self._chunk_matrix = np.empty((0, 0), dtype=np.float32)
        self._chunk_refs = refs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def stats(self) -> Dict[str, int]:
        async with self._lock:
            chunk_count = sum(len(doc.get("chunks") or []) for doc in self.documents)
            return {
                "document_count": len(self.documents),
                "chunk_count": chunk_count,
            }

    async def list_documents(self) -> List[Dict[str, Any]]:
        async with self._lock:
            items: List[Dict[str, Any]] = []
            for doc in self.documents:
                raw_text = (doc.get("text") or "").strip().replace("\r\n", " ").replace("\n", " ")
                preview = raw_text[:160] + ("…" if len(raw_text) > 160 else "")
                metadata = doc.get("metadata")
                if not metadata and isinstance(doc.get("meta"), dict):  # backward compatibility
                    metadata = doc.get("meta")
                items.append({
                    "id": doc.get("id"),
                    "preview": preview,
                    "chunks": len(doc.get("chunks") or []),
                    "created_at": doc.get("created_at"),
                    "metadata": metadata or {},
                })
            return items

    async def clear(self) -> None:
        async with self._lock:
            self.documents = []
            self._rebuild_index()
            self._save()

    async def delete_document(self, doc_id: str) -> bool:
        async with self._lock:
            original_len = len(self.documents)
            self.documents = [doc for doc in self.documents if doc.get("id") != doc_id]
            removed = len(self.documents) != original_len
            if removed:
                self._rebuild_index()
                self._save()
            return removed

    async def add_document(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Skriv in text att lägga till i kunskapsbasen.")
        chunks = self._chunk_text(cleaned)
        if not chunks:
            raise ValueError("Kunde inte dela upp texten i utdrag.")

        embeddings: List[List[float]] = []
        for chunk in chunks:
            embedding = await self._embed_text(chunk)
            embeddings.append([float(x) for x in embedding])

        doc_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        stored_chunks = []
        for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            stored_chunks.append({
                "index": idx,
                "text": chunk_text,
                "embedding": embedding,
            })
        new_doc = {
            "id": doc_id,
            "text": cleaned,
            "chunks": stored_chunks,
            "created_at": created_at,
            "metadata": metadata or {},
        }
        async with self._lock:
            self.documents.append(new_doc)
            self._rebuild_index()
            self._save()
        preview = cleaned[:160] + ("…" if len(cleaned) > 160 else "")
        return {
            "id": doc_id,
            "preview": preview,
            "chunks": len(stored_chunks),
            "created_at": created_at,
            "metadata": metadata or {},
        }

    async def search(self, query: str, top_k: int = 3) -> List[RAGResult]:
        question = (query or "").strip()
        if not question:
            return []
        top_k = max(1, min(int(top_k), 10))
        async with self._lock:
            if not self._chunk_refs or self._chunk_matrix.size == 0:
                return []
            matrix = self._chunk_matrix.copy()
            refs = list(self._chunk_refs)
        embedding = await self._embed_text(question)
        query_vec = np.asarray(embedding, dtype=np.float32)
        q_norm = np.linalg.norm(query_vec)
        if q_norm == 0:
            return []
        query_vec /= q_norm
        scores = matrix @ query_vec
        if scores.ndim == 0:
            scores = np.asarray([float(scores)])
        ranked_indices = np.argsort(scores)[::-1][:top_k]
        results: List[RAGResult] = []
        for idx in ranked_indices:
            ref = refs[int(idx)]
            results.append(RAGResult(
                doc_id=str(ref.get("doc_id")),
                chunk_index=int(ref.get("chunk_index", 0)),
                text=str(ref.get("text", "")),
                score=float(scores[int(idx)]),
            ))
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _chunk_text(self, text: str, max_chars: int = 600) -> List[str]:
        norm = text.replace("\r\n", "\n")
        paragraphs = [p.strip() for p in norm.split("\n\n") if p.strip()]
        chunks: List[str] = []
        for para in paragraphs:
            part = para
            while len(part) > max_chars:
                split_at = part.rfind(" ", 0, max_chars)
                if split_at <= 0:
                    split_at = max_chars
                chunk = part[:split_at].strip()
                if chunk:
                    chunks.append(chunk)
                part = part[split_at:].strip()
            if part:
                chunks.append(part)
        if not chunks and norm:
            chunks.append(norm[:max_chars])
        return chunks

    async def _embed_text(self, text: str) -> List[float]:
        url = f"{self.ollama_host}/api/embeddings"
        payload = {
            "model": self.embed_model,
            "prompt": text,
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # type: ignore[no-untyped-def]
            detail = exc.response.text
            raise RuntimeError(
                f"Kunde inte generera embedding ({exc.response.status_code}): {detail}"
            ) from exc
        except httpx.HTTPError as exc:  # type: ignore[no-untyped-def]
            raise RuntimeError(f"Kunde inte nå Ollama för embedding: {exc}") from exc

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama svarade med ogiltig JSON för embeddings.") from exc

        embedding: Optional[List[float]] = None
        raw_embedding = data.get("embedding")
        if isinstance(raw_embedding, list):
            embedding = raw_embedding
        else:
            data_list = data.get("data")
            if isinstance(data_list, list) and data_list:
                first = data_list[0] if isinstance(data_list[0], dict) else None
                maybe_embedding = first.get("embedding") if isinstance(first, dict) else None
                if isinstance(maybe_embedding, list):
                    embedding = maybe_embedding
        if embedding is None:
            raise RuntimeError("Embedding saknas i svaret från Ollama. Kontrollera att modellen stödjer embeddings.")
        return embedding
