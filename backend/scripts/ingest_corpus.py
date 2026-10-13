"""批量灌语料：遍历 backend/data/corpus/，走 KnowledgeService 入库。

用法（cwd = backend/）：
    python -m scripts.ingest_corpus --dry-run     # 只统计，不碰向量库
    python -m scripts.ingest_corpus --rebuild     # 先清空 collection，再全量重建
    python -m scripts.ingest_corpus --only javaguide   # 只灌某个子目录

语料目录 backend/data/corpus/ 已在 .gitignore 内（体量 + 授权都不进 git）：
  javaguide/            Snailclimb/JavaGuide 的 docs/ 核心章节（Apache-2.0）
  01.阿里篇 … 21.面经/   0voice/interview_internal_reference
  my-notes/             自己的 Java 笔记

边界：只调用既有公开接口（document_loader.load / get_splitter /
KnowledgeService.upload_document + 向量库的 collection 句柄），不改任何现有模块。
"""
import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from app.core.config import settings
from app.infrastructure.document_loader import load
from app.infrastructure.text_splitter import get_splitter

DEFAULT_CORPUS_DIR = "data/corpus"
SKIP_NAMES = {
    "README.md", "readme.md",   # 纯目录/TOC 索引，没有答案，检索价值低
    "test.md", "test.txt",      # 残留测试文件
    # C/C++ 千题：429 chunk 会塞进单个 embedding 请求（超上限），且与 Java/RAG 求职方向无关。
    # 想加回来就把这行删掉——文件仍在 corpus/ 下，不需要重新下载。
    "2023adding.md",
}

# add_documents() 会把一个文档的全部 chunk 塞进**单个** embedding 请求，
# 超过这个数就单独标出来（很可能被厂商拒或超时）。
BATCH_WARN_CHUNKS = 128


def discover(corpus_dir: Path, only: list[str] | None) -> list[Path]:
    """递归收集语料文件，按扩展名白名单过滤。"""
    allowed = {e.lower() for e in settings.ALLOWED_EXTENSIONS}
    found = []
    for p in sorted(corpus_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in allowed:
            continue
        if p.name in SKIP_NAMES:
            continue
        if only:
            first = p.relative_to(corpus_dir).parts[0]
            if first not in only:
                continue
        found.append(p)
    return found


def count_chunks(files: list[Path], corpus_dir: Path) -> tuple[list[dict], list[tuple[Path, str]]]:
    """只读解析 + 切分，返回统计明细与失败清单。不触碰向量库。"""
    splitter = get_splitter()
    rows, failed = [], []
    for path in files:
        try:
            text = load(str(path))
            chunks = splitter.split_text(text)
        except Exception as e:
            failed.append((path, str(e)))
            continue
        rows.append({
            "path": path,
            "group": path.relative_to(corpus_dir).parts[0] if len(path.relative_to(corpus_dir).parts) > 1 else ".",
            "chars": len(text),
            "chunks": len(chunks),
        })
    return rows, failed


def print_report(rows: list[dict], failed: list[tuple[Path, str]], corpus_dir: Path) -> None:
    by_group = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        by_group[r["group"]][0] += 1
        by_group[r["group"]][1] += r["chunks"]
        by_group[r["group"]][2] += r["chars"]

    print(f"\n{'来源':<36}{'篇数':>6}{'chunk':>8}{'字符':>10}")
    print("-" * 60)
    for g in sorted(by_group):
        n, c, ch = by_group[g]
        print(f"{g:<36}{n:>6}{c:>8}{ch:>10}")
    print("-" * 60)
    total_chunks = sum(r["chunks"] for r in rows)
    total_chars = sum(r["chars"] for r in rows)
    print(f"{'合计':<36}{len(rows):>6}{total_chunks:>8}{total_chars:>10}")

    empty = [r for r in rows if r["chunks"] == 0]
    if empty:
        print(f"\n切不出 chunk（空文件），将跳过 ({len(empty)})：")
        for r in empty[:20]:
            print(f"  {r['chars']:>8} 字符  {r['path'].relative_to(corpus_dir)}")
        if len(empty) > 20:
            print(f"  ... 其余 {len(empty) - 20} 个")

    big = sorted([r for r in rows if r["chunks"] > BATCH_WARN_CHUNKS],
                 key=lambda r: -r["chunks"])
    if big:
        print(f"\n[!] 单文档 chunk 数 > {BATCH_WARN_CHUNKS}（embedding 单请求风险）：")
        for r in big:
            print(f"  {r['chunks']:>5} chunk  {r['path'].relative_to(corpus_dir)}")

    if failed:
        print(f"\n解析失败 ({len(failed)})：")
        for path, err in failed[:20]:
            print(f"  {path.relative_to(corpus_dir)}: {err}")


def clear_collection(store) -> int:
    """清空 collection（Chroma 没有 drop-all，只能先取全量 id 再删）。"""
    ids = store.collection.get(include=["metadatas"]).get("ids", [])
    if ids:
        store.collection.delete(ids=ids)
    return len(ids)


async def ingest(files: list[Path], corpus_dir: Path) -> None:
    from app.services.knowledge_service import get_knowledge_service

    svc = get_knowledge_service()
    ok, failed = 0, []
    for i, path in enumerate(files, 1):
        rel = path.relative_to(corpus_dir)
        try:
            result = await svc.upload_document(str(path), path.name)
            ok += 1
            print(f"[{i}/{len(files)}] {result['chunk_count']:>4} chunk  {rel}")
        except Exception as e:
            failed.append((rel, str(e)))
            print(f"[{i}/{len(files)}] 失败  {rel}: {e}")

    print(f"\n入库完成：成功 {ok} 篇，失败 {len(failed)} 篇")
    for rel, err in failed:
        print(f"  失败  {rel}: {err}")


def main() -> int:
    # Windows 控制台默认 GBK，中文路径/标题会乱码甚至抛 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="批量灌语料到向量库")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_DIR, help="语料目录")
    parser.add_argument("--dry-run", action="store_true", help="只统计并打印报告，不写向量库")
    parser.add_argument("--rebuild", action="store_true", help="先清空 collection 再重建")
    parser.add_argument("--only", default="", help="只处理这些顶层子目录，逗号分隔")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    if not corpus_dir.is_dir():
        print(f"语料目录不存在: {corpus_dir.resolve()}", file=sys.stderr)
        return 1

    only = [s.strip() for s in args.only.split(",") if s.strip()] or None
    files = discover(corpus_dir, only)
    if not files:
        print(f"没有可处理的文件（扩展名白名单 {settings.ALLOWED_EXTENSIONS}）", file=sys.stderr)
        return 1

    mode = "DRY-RUN（不写库）" if args.dry_run else ("REBUILD（先清空）" if args.rebuild else "APPEND")
    print(f"语料目录: {corpus_dir.resolve()}")
    print(f"模式: {mode}   chunk_size={settings.CHUNK_SIZE} chunk_overlap={settings.CHUNK_OVERLAP}")
    print(f"发现 {len(files)} 个文件")

    rows, failed = count_chunks(files, corpus_dir)
    print_report(rows, failed, corpus_dir)

    if args.dry_run:
        print("\n（dry-run 结束，向量库未改动）")
        return 0

    if not args.rebuild:
        print("\n[!] 未指定 --rebuild：本次为追加，同一文件会生成新的 document_id（产生重复文档）。")
        print("   语料重建请用 --rebuild。5 秒内 Ctrl-C 可取消。")
        try:
            import time
            time.sleep(5)
        except KeyboardInterrupt:
            print("已取消")
            return 130

    usable = [r["path"] for r in rows if r["chunks"] > 0]
    skipped = len(rows) - len(usable)
    if skipped:
        print(f"跳过 {skipped} 个空文件（解析后无内容，入库会被拒）")
    if args.rebuild:
        from app.repositories.vector_store import get_vector_store
        removed = clear_collection(get_vector_store())
        print(f"已清空 collection，删除 {removed} 条旧 chunk")

    asyncio.run(ingest(usable, corpus_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
