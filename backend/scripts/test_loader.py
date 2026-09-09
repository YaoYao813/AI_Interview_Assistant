"""文档加载器测试脚本"""
from app.infrastructure.document_loader import DocumentLoader

DATA_DIR = "data/documents"

FILES = ["test.txt", "test.md"]

if __name__ == "__main__":
    loader = DocumentLoader()
    for name in FILES:
        path = f"{DATA_DIR}/{name}"
        try:
            text = loader.load(path)
            print(f"=== {name} ({len(text)} 字符) ===\n{text}\n")
        except Exception as e:
            print(f"=== {name} 失败 ===\n{e}\n")
