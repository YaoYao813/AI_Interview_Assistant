"""
文档加载器
职责：将 PDF/DOCX/MD/TXT 文件解析为纯文本
设计：扩展名分发器模式，新增格式只需加一个解析函数
依赖：
  pypdf        - PDF 解析
  python-docx  - Word 解析
"""
import re
from pathlib import Path

class DocumentLoader:
    """统一文档加载器，按扩展名分发到对应的解析函数"""

    # ===== 分发器映射 =====
    _PARSERS: dict[str, str] = {
        ".pdf": "parse_pdf",
        ".docx": "parse_docx",
        ".doc": "parse_docx",
        ".md": "parse_markdown",
        ".txt": "parse_text",
    }

    # ===== 公共入口 =====
    def load(self, file_path: str) -> str:
        """
        统一文档加载接口

        Args:
            file_path: 文件绝对路径

        Returns:
            解析后的纯文本内容

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 格式不支持或解析失败
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = path.suffix.lower()
        method_name = self._PARSERS.get(ext)
        if method_name is None:
            raise ValueError(f"不支持的文档格式: {ext}")

        parser = getattr(self, method_name)
        try:
            raw = parser(str(path))
            return self._normalize(raw)
        except Exception as e:
            raise ValueError(f"文档解析失败 ({path.name}): {e}") from e

    # ===== PDF =====

    def parse_pdf(self, file_path: str) -> str:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
        return "\n".join(parts)

    # ===== DOCX =====

    _HEADING_PREFIX: dict[str, str] = {
        "Heading 1": "# ",
        "Heading 2": "## ",
        "Heading 3": "### ",
    }

    def parse_docx(self, file_path: str) -> str:
        from docx import Document
        doc = Document(file_path)
        lines: list[str] = []
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            prefix = self._HEADING_PREFIX.get(p.style.name, "")
            lines.append(prefix + text)
        return "\n".join(lines)

    # ===== Markdown =====

    def parse_markdown(self, file_path: str) -> str:
        return Path(file_path).read_text(encoding="utf-8")

    # ===== TXT =====

    def parse_text(self, file_path: str) -> str:
        return Path(file_path).read_text(encoding="utf-8")

    # ===== 后处理 =====

    def _normalize(self, text: str) -> str:
        """统一后处理：合并多余空行、去除首尾空白"""
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# ===== 模块级快捷函数 =====

_loader: DocumentLoader | None = None


def _get_loader() -> DocumentLoader:
    global _loader
    if _loader is None:
        _loader = DocumentLoader()
    return _loader


def load(file_path: str) -> str:
    """模块级快捷入口：加载文档为纯文本"""
    return _get_loader().load(file_path)


def get_file_info(file_path: str) -> dict:
    """获取文件基本信息（扩展名、大小等）"""
    path = Path(file_path)
    return {
        "filename": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def get_supported_extensions() -> list[str]:
    """返回支持的文件扩展名列表"""
    return list(DocumentLoader._PARSERS.keys())
