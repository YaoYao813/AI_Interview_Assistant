"""文本切分器测试脚本"""
from app.infrastructure.document_loader import DocumentLoader
from app.infrastructure.text_splitter import get_splitter, reset_splitter

DATA_DIR = "data/documents"
FILE = "test.txt"

if __name__ == "__main__":
    reset_splitter()

    # 加载
    loader = DocumentLoader()
    path = f"{DATA_DIR}/{FILE}"
    text = loader.load(path)

    # 切分
    splitter = get_splitter()
    chunks = splitter.split_text(text)
    estimate = splitter.estimate_chunk_count(text)

    print(f"文件: {FILE}")
    print(f"原文: {len(text)} 字符")
    print(f"配置: {splitter.config}")
    print(f"估算: {estimate} 块 | 实际: {len(chunks)} 块")
    print()

    for c in chunks:
        preview = c["content"][:100].replace("\n", "\\n")
        print(f"--- 块 {c['chunk_index']} | {c['chunk_size']} 字符 | 起始 {c['start_index']} ---")
        print(preview)
        print()
