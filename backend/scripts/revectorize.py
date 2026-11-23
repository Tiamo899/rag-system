"""重灌向量：按当前分块策略重新解析 → 切块 → 嵌入 → 写 ES/PG。

用途：改了分块参数（chunk_size / 合并下限 / 解析器）后，让存量文档重新入库。
单文档幂等（先删同 doc 的 ES 文档与 PG 分块，再写），可重复执行。

用法（backend/ 目录）：
    python -m scripts.revectorize                  # 全部未废止文档
    python -m scripts.revectorize --kb-id <kb_id>  # 只重灌某个知识库
    python -m scripts.revectorize --dry-run        # 只打印分块统计，不写库
"""
import argparse
import asyncio
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models import Document, KnowledgeBase  # noqa: E402
from app.services.chunking.splitter import split_text  # noqa: E402
from app.services.document_parser.factory import get_parser  # noqa: E402
from app.services.vectorizer import _do_vectorize  # noqa: E402


def _strategy(doc: Document) -> str:
    return "markdown" if doc.file_type in ("markdown", "word") else "fixed"


def _chunk_stats(chunks: list[str]) -> str:
    if not chunks:
        return "空"
    lens = [len(c) for c in chunks]
    return (
        f"{len(chunks)} 块 / 中位 {int(statistics.median(lens))} 字 / "
        f"最短 {min(lens)} / 最长 {max(lens)} / 合计 {sum(lens)} 字"
    )


async def main(kb_id: str | None, dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        stmt = select(Document).where(Document.superseded_by.is_(None))
        if kb_id:
            stmt = stmt.where(Document.kb_id == kb_id)
        docs = (await db.execute(stmt)).scalars().all()
        print(f"待处理文档 {len(docs)} 份{'（dry-run，只统计不写库）' if dry_run else ''}")

        total_chunks = 0
        for i, doc in enumerate(docs, 1):
            kb = await db.get(KnowledgeBase, doc.kb_id)
            name = doc.original_name
            try:
                text = await asyncio.to_thread(get_parser(doc.file_type).parse, doc.file_path)
                chunks = split_text(
                    text, kb.chunk_size, kb.chunk_overlap, strategy=_strategy(doc)
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{i}/{len(docs)}] {name} 解析失败: {exc}")
                continue

            print(f"[{i}/{len(docs)}] {name} → {_chunk_stats(chunks)}")
            total_chunks += len(chunks)
            if dry_run or not chunks:
                continue

            try:
                await _do_vectorize(db, doc)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                print(f"    向量化失败: {exc}")

        print(f"完成，共 {total_chunks} 个分块")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按当前分块策略重灌向量")
    parser.add_argument("--kb-id", default=None, help="只处理指定知识库")
    parser.add_argument("--dry-run", action="store_true", help="只统计分块，不写库")
    args = parser.parse_args()
    asyncio.run(main(args.kb_id, args.dry_run))
