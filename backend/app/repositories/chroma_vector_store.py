import logging
from datetime import datetime, timezone

import chromadb

from app.core.config import settings
from app.infrastructure.embeddings import get_embedding
from app.repositories.base_vector_store import BaseVectorStore, DocumentChunk, DocumentInfo, SearchResult

logger = logging.getLogger(__name__)

# 候选池下限。Chroma 的 HNSW 是近似检索，n_results 同时决定搜索强度：
# 给小了，返回的 top-k 本身就不准，跟阈值无关。实测（2393 chunk / 31 条真实问题）
# n_results=5 拿到的 top-5 有 13/31 与收敛结果不同，20 → 8/31，100 → 0/31。
# 所以先取大池、后过滤、最后截断到 top_k；池子大小以「前 5 名不再随 n_results 变」为准。
_POOL_MIN = 100


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
        file_size: int | None = None,
    ) -> int:
        if not chunks:
            return 0

        texts = [c["content"] for c in chunks]
        embeddings = await get_embedding().embed_documents(texts)

        ids = [f"{document_id}_{c['chunk_index']}" for c in chunks]
        created_at = datetime.now(timezone.utc).isoformat()
        metadatas = []
        for c in chunks:
            meta = {
                "document_id": document_id,
                "filename": filename,
                "chunk_index": c["chunk_index"],
                "chunk_size": c.get("chunk_size", len(c["content"])),
                "created_at": created_at,
            }
            # Chroma 的 metadata 不接受 None，缺大小就整个字段不写
            if file_size is not None:
                meta["file_size"] = file_size
            metadatas.append(meta)

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
        # 相对底线：ratio>0 时把绝对 threshold 抬到 top1 的一个比例。
        # Chroma 按距离升序返回，第 0 条即最高分。ratio=0 时完全不介入，
        # threshold 的原语义（含 -1 = 真不过滤）原样保留。
        floor = threshold
        ratio = settings.RETRIEVAL_RELATIVE_RATIO

        pool = max(top_k, _POOL_MIN)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=pool,
        )

        ids_list = result.get("ids", [[]])[0]
        docs_list = result.get("documents", [[]])[0]
        metas_list = result.get("metadatas", [[]])[0]
        distances_list = result.get("distances", [[]])[0]

        if ratio > 0 and distances_list:
            floor = max(floor, ratio * round(1 - distances_list[0], 4))

        hits: list[DocumentChunk] = []
        for i in range(len(ids_list)):
            doc_id = ids_list[i]
            document = docs_list[i] if i < len(docs_list) else ""
            metadata = metas_list[i] if i < len(metas_list) else {}
            distance = distances_list[i] if i < len(distances_list) else 0
            chunk = DocumentChunk.from_chroma(doc_id, document, metadata, distance)
            if chunk.similarity is not None and chunk.similarity < floor:
                logger.debug("过滤低相似度: id=%s similarity=%.4f", doc_id, chunk.similarity)
                continue
            hits.append(chunk)

        # 池子是按 _POOL_MIN 取的，截断必须放最后，否则又变成「先截断后过滤」
        hits = hits[:top_k]

        logger.info("搜索完成: pool=%d top_k=%d floor=%.4f 命中=%d 距离=%s",
                    pool, top_k, floor, len(hits), distances_list)
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

    def get_document_stats(self) -> dict:
        """一次扫描算出文档级汇总。

        每个 chunk 的 metadata 都冗余存了文档级字段，按 document_id 去重时
        顺带把大小累加了，不必为「总大小」再扫一遍。
        """
        all_data = self.collection.get(include=["metadatas"])
        metadatas = all_data.get("metadatas", [])
        size_by_doc: dict[str, int | None] = {}
        for m in metadatas:
            if not m:
                continue
            doc_id = m.get("document_id")
            if doc_id and doc_id not in size_by_doc:
                size_by_doc[doc_id] = m.get("file_size")

        sizes = [s for s in size_by_doc.values() if s is not None]
        return {
            "document_count": len(size_by_doc),
            "sized_document_count": len(sizes),
            "total_size": sum(sizes),
        }

    def get_chunk_count(self) -> int:
        return self.collection.count()

    # ===== 列表 =====

    def list_documents(
        self,
        limit: int = 20,
        offset: int = 0,
        keyword: str = "",
        extension: str | None = None,
    ) -> tuple[list[DocumentInfo], int]:
        """分页列出文档概要。

        **注意：这一步仍是全量扫描**。Chroma 没有 group by，要按 document_id
        聚合就必须把全部 chunk 的 metadata 拉回来；分页省下的是传输量与
        前端内存，不是扫描本身。真正的 O(页) 需要给每个文档额外写一条
        manifest 记录、再用 where 过滤（本项目未做）。
        """
        all_data = self.collection.get(include=["metadatas"])
        ids = all_data.get("ids", [])
        metadatas = all_data.get("metadatas", [])
        if not ids:
            return [], 0

        # 按 document_id 聚合
        doc_map: dict[str, DocumentInfo] = {}
        for i in range(len(ids)):
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
                    file_size=meta.get("file_size"),
                )
            doc_map[doc_id].chunk_count += 1

        docs = list(doc_map.values())
        docs.sort(key=lambda d: d.created_at, reverse=True)

        # 过滤放在服务端：分页前过滤，total 才是「匹配到的总数」，
        # 否则搜索只会搜当前这一页
        kw = keyword.strip().lower()
        if kw:
            docs = [d for d in docs if kw in d.filename.lower()]
        if extension:
            ext = extension.lower()
            docs = [d for d in docs if d.filename.lower().endswith(ext)]

        total = len(docs)
        return docs[offset:offset + limit], total

    # ===== 健康检查 =====

    def health_check(self) -> dict:
        """轻量探针，供 /health 这类高频调用使用。

        刻意只用 count()，不调 get_document_stats()——后者是
        `collection.get(include=["metadatas"])` 的全量扫描，
        把一个每秒可能被探测多次的接口变成反复全表拉取。
        """
        return {
            "status": "ok",
            "chunk_count": self.get_chunk_count(),
        }
