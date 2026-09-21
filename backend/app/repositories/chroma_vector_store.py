import logging
from datetime import datetime, timezone

import chromadb

from app.infrastructure.embeddings import get_embedding
from app.repositories.base_vector_store import BaseVectorStore, DocumentChunk, DocumentInfo, SearchResult

logger = logging.getLogger(__name__)


class ChromaVectorStore(BaseVectorStore):
    """基于 ChromaDB 的向量存储实现"""

    def __init__(self, persist_dir: str, collection_name: str):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ===== 写入 =====

    async def add_documents(
        self,
        chunks: list[dict],
        document_id: str,
        filename: str,
    ) -> int:
        if not chunks:
            return 0

        texts = [c["content"] for c in chunks]
        embeddings = await get_embedding().embed_documents(texts)

        ids = [f"{document_id}_{c['chunk_index']}" for c in chunks]
        created_at = datetime.now(timezone.utc).isoformat()
        metadatas = [
            {
                "document_id": document_id,
                "filename": filename,
                "chunk_index": c["chunk_index"],
                "chunk_size": c.get("chunk_size", len(c["content"])),
                "created_at": created_at,
            }
            for c in chunks
        ]

        self.collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return len(chunks)

    # ===== 查询 =====

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        threshold: float = 0.3,
    ) -> SearchResult:

        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        ids_list = result.get("ids", [[]])[0]
        docs_list = result.get("documents", [[]])[0]
        metas_list = result.get("metadatas", [[]])[0]
        distances_list = result.get("distances", [[]])[0]

        hits: list[DocumentChunk] = []
        for i in range(len(ids_list)):
            doc_id = ids_list[i]
            document = docs_list[i] if i < len(docs_list) else ""
            metadata = metas_list[i] if i < len(metas_list) else {}
            distance = distances_list[i] if i < len(distances_list) else 0
            chunk = DocumentChunk.from_chroma(doc_id, document, metadata, distance)
            if chunk.similarity is not None and chunk.similarity < threshold:
                logger.debug("过滤低相似度: id=%s similarity=%.4f", doc_id, chunk.similarity)
                continue
            hits.append(chunk)

        logger.info("搜索完成: top_k=%d threshold=%.2f 命中=%d 距离=%s",
                    top_k, threshold, len(hits), distances_list)
        return SearchResult(hits=hits, total=len(hits))

    # ===== 删除 =====

    def delete_document(self, document_id: str) -> int:
        all_data = self.collection.get(include=["metadatas"])
        all_ids = all_data.get("ids", [])
        all_metas = all_data.get("metadatas", [])
        chunk_ids = [
            all_ids[i] for i in range(len(all_ids))
            if i < len(all_metas) and all_metas[i]
            and all_metas[i].get("document_id") == document_id
        ]
        if not chunk_ids:
            return 0

        self.collection.delete(ids=chunk_ids)
        return len(chunk_ids)

    # ===== 统计 =====

    def get_document_count(self) -> int:
        all_data = self.collection.get(include=["metadatas"])
        metadatas = all_data.get("metadatas", [])
        doc_ids = {m["document_id"] for m in metadatas if m and "document_id" in m}
        return len(doc_ids)

    def get_chunk_count(self) -> int:
        return self.collection.count()

    # ===== 列表 =====

    def list_documents(self, limit: int = 100) -> list[DocumentInfo]:
        all_data = self.collection.get(include=["metadatas"])
        ids = all_data.get("ids", [])
        metadatas = all_data.get("metadatas", [])
        if not ids:
            return []

        # 按 document_id 聚合
        doc_map: dict[str, DocumentInfo] = {}
        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            if not meta:
                continue
            doc_id = meta.get("document_id", "")
            if not doc_id:
                continue

            if doc_id not in doc_map:
                doc_map[doc_id] = DocumentInfo(
                    document_id=doc_id,
                    filename=meta.get("filename", ""),
                    chunk_count=0,
                    created_at=meta.get("created_at", ""),
                )
            doc_map[doc_id].chunk_count += 1

        result = list(doc_map.values())
        result.sort(key=lambda d: d.created_at, reverse=True)
        return result[:limit]

    # ===== 健康检查 =====

    def health_check(self) -> dict:
        """轻量探针，供 /health 这类高频调用使用。

        刻意只用 count()，不调 get_document_count()——后者是
        `collection.get(include=["metadatas"])` 的全量扫描，
        把一个每秒可能被探测多次的接口变成反复全表拉取。
        """
        return {
            "status": "ok",
            "chunk_count": self.get_chunk_count(),
        }
