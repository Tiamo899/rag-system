"""ES 索引管理：mapping 常量 + ensure_index（含 dims 一致性校验）。"""
from elasticsearch import AsyncElasticsearch

from app.core.config import get_settings
from app.core.elasticsearch import get_es

_settings = get_settings()


def chunk_index_mapping() -> dict:
    """chunk 索引 mapping。dims 与 EMBEDDING_DIM 同源。"""
    return {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "kb_id": {"type": "keyword"},
            "content": {"type": "text", "analyzer": "ik_max_word"},
            "content_vector": {
                "type": "dense_vector",
                "dims": _settings.embedding_dim,
                # 8.11 起 index:true 废弃，改用 index_options(HNSW)
                "index_options": {"type": "hnsw", "m": 16, "ef_construction": 100},
                "similarity": "cosine",
            },
            "metadata": {
                "type": "object",
                "properties": {
                    "valid_from": {"type": "date", "format": "yyyy-MM-dd||strict_date_optional_time"},
                    "valid_to": {"type": "date", "format": "yyyy-MM-dd||strict_date_optional_time"},
                    "version_no": {"type": "keyword"},
                },
            },
            "created_at": {"type": "date"},
        }
    }


async def ensure_index(es: AsyncElasticsearch | None = None) -> None:
    """启动时调用：索引不存在则创建；已存在则校验 dims（不可原地修改）。"""
    es = es or get_es()
    index = _settings.es_index

    if not await es.indices.exists(index=index):
        await es.indices.create(index=index, mappings=chunk_index_mapping())
        return

    info = await es.indices.get(index=index)
    props = info[index]["mappings"]["properties"]
    existing_dims = props.get("content_vector", {}).get("dims")
    if existing_dims != _settings.embedding_dim:
        raise RuntimeError(
            f"ES 索引 {index} 的 dims={existing_dims} 与配置 EMBEDDING_DIM="
            f"{_settings.embedding_dim} 不一致，请删除索引重建后再启动"
        )
    # 存量索引补 metadata 子映射（幂等；与新建 mapping 保持一致）
    await es.indices.put_mapping(
        index=index,
        properties={"metadata": chunk_index_mapping()["properties"]["metadata"]},
    )
