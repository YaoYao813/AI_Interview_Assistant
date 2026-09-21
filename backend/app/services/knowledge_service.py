"""
知识库管理服务
职责：文档上传、删除、列表查询的编排层
设计：协调 document_loader → text_splitter → vector_store 三个基础设施

类比 Java：
  KnowledgeService  → 类似 @Service 类
  编排多个底层组件   → 类似 Service 中调用多个 DAO/Util
"""
import logging
import os
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timezone

from app.core.config import settings
from app.core.exceptions import NotFoundException, InvalidFileException
from app.infrastructure.document_loader import load, get_file_info, get_supported_extensions
from app.infrastructure.text_splitter import get_splitter
from app.repositories.vector_store import get_vector_store, DocumentInfo


class KnowledgeService:
    """
    知识库管理服务

    职责范围：
      - 上传文档（解析 → 切片 → 向量化 → 存储）
      - 删除文档
      - 文档列表查询
      - 文档统计信息

    不负责：
      - RAG 问答（由 RAGService 负责）
      - 文件格式解析（由 document_loader 负责）
    """

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._splitter = get_splitter()
        self._vector_store = get_vector_store()

    # ========== 上传文档 ==========

    async def upload_document(self, file_path: str, original_filename: str) -> dict:
        """
        上传并索引文档

        完整流程：
          1. 文件校验（扩展名、大小）
          2. 解析文档为纯文本
          3. 切分为文本块
          4. 向量化并存入 Chroma
          5. 返回文档概要信息

        Args:
            file_path: 上传文件在服务端的绝对路径
            original_filename: 用户上传时的原始文件名（用于展示）

        Returns:
            {
                "document_id": str,
                "filename": str,
                "chunk_count": int,
                "status": "success",
            }

        Raises:
            InvalidFileException: 格式不支持、文件过大、解析失败
        """
        # 1. 前置校验
        self._validate_file(file_path, original_filename)

        # 2. 生成唯一文档 ID（UUID 前 8 位 + 时间戳，便于识别）
        document_id = self._generate_document_id(original_filename)

        try:
            # 3. 解析文档
            text = load(file_path)

            # 4. 切分为 chunks
            chunks = self._splitter.split_text(text)

            if not chunks:
                raise InvalidFileException("文档解析后内容为空，无法索引")

            # 5. 存入向量库
            chunk_count = await self._vector_store.add_documents(
                chunks=chunks,
                document_id=document_id,
                filename=original_filename,
            )

            return {
                "document_id": document_id,
                "filename": original_filename,
                "chunk_count": chunk_count,
                "status": "success",
            }

        except Exception as e:
            # 上传失败时清理已保存的文件（不会污染文件系统）
            self._cleanup_on_failure(file_path)
            raise e

    async def upload_document_from_bytes(
        self,
        file_bytes: bytes,
        original_filename: str,
    ) -> dict:
        """
        从字节流上传文档（API 层接收前端 multipart 上传后调用）

        流程：
          1. 将字节流保存到临时文件
          2. 调用 upload_document
          3. 清理临时文件
        """
        # 校验扩展名（先校验再写盘）
        ext = Path(original_filename).suffix.lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise InvalidFileException(
                f"不支持的文件格式 '{ext}'。"
                f"当前支持: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )

        # 确保上传目录存在
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 写入临时文件（使用 UUID 防止文件名冲突）
        temp_filename = f"{uuid.uuid4().hex}{ext}"
        temp_path = upload_dir / temp_filename

        try:
            with open(temp_path, "wb") as f:
                f.write(file_bytes)

            return await self.upload_document(str(temp_path), original_filename)

        finally:
            # 无论成功失败，清理临时文件
            if temp_path.exists():
                temp_path.unlink()

    # ========== 删除文档 ==========

    def delete_document(self, document_id: str) -> int:
        """
        删除文档及其所有文本块

        Args:
            document_id: 文档唯一 ID

        Returns:
            实际删除的文本块数量

        Raises:
            NotFoundException: 文档不存在
        """
        affected = self._vector_store.delete_document(document_id)

        if affected == 0:
            raise NotFoundException(f"文档不存在或已被删除: {document_id}")

        return affected

    # ========== 查询 ==========

    def list_documents(self) -> list[dict]:
        """
        获取文档列表（按上传时间倒序）

        Returns:
            [
                {
                    "document_id": str,
                    "filename": str,
                    "chunk_count": int,
                    "created_at": str,
                },
                ...
            ]
        """
        documents = self._vector_store.list_documents()
        return [doc.to_dict() for doc in documents]

    def get_statistics(self) -> dict:
        """
        获取知识库统计信息

        Returns:
            {
                "document_count": int,
                "chunk_count": int,
            }
        """
        return {
            "document_count": self._vector_store.get_document_count(),
            "chunk_count": self._vector_store.get_chunk_count(),
        }

    # ========== 私有方法 ==========

    def _validate_file(self, file_path: str, original_filename: str) -> None:
        """
        文件校验（前置检查）

        Checks:
          - 扩展名是否在白名单内
          - 文件大小是否超过限制
        """
        # 校验扩展名
        ext = Path(original_filename).suffix.lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise InvalidFileException(
                f"不支持的文件格式 '{ext}'。"
                f"当前支持: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )

        # 校验文件大小
        file_size = Path(file_path).stat().st_size
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            raise InvalidFileException(
                f"文件过大（{file_size / 1024 / 1024:.1f}MB），"
                f"请上传小于 {settings.MAX_UPLOAD_SIZE_MB}MB 的文件"
            )

        # 校验文件不为空
        if file_size == 0:
            raise InvalidFileException("上传文件为空")

    def _generate_document_id(self, filename: str) -> str:
        """
        生成唯一文档 ID

        格式：{UUID前8位}_{时间戳}_{文件名前缀}
        示例：a1b2c3d4_20240101_Java集合

        这样生成的 ID 即使不查数据库也能大致知道是什么文档
        """
        short_uuid = uuid.uuid4().hex[:8]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        name_prefix = Path(filename).stem.replace(" ", "_")[:20]
        return f"{short_uuid}_{timestamp}_{name_prefix}"

    def _cleanup_on_failure(self, file_path: str) -> None:
        """
        上传失败时的清理

        如果文件在 upload_document 的 try 块之前就已经存在，
        这里不删（因为不是本次上传创建的）。
        只在文件位于 UPLOAD_DIR 时才清理。
        """
        try:
            upload_dir = Path(settings.UPLOAD_DIR).resolve()
            file_path_resolved = Path(file_path).resolve()
            if upload_dir in file_path_resolved.parents and file_path_resolved.exists():
                file_path_resolved.unlink()
                self._logger.info("清理失败上传的临时文件: %s", file_path)
        except Exception:
            pass  # 清理失败不影响主流程


# ========== 全局单例 ==========

_knowledge_service_instance: KnowledgeService | None = None


def get_knowledge_service() -> KnowledgeService:
    """获取 KnowledgeService 单例"""
    global _knowledge_service_instance
    if _knowledge_service_instance is None:
        _knowledge_service_instance = KnowledgeService()
    return _knowledge_service_instance


def reset_knowledge_service() -> None:
    """重置单例（测试用）"""
    global _knowledge_service_instance
    _knowledge_service_instance = None
