"""系统配置 API（只读展示）。

配置运行时从 backend/.env（pydantic-settings）读取，DB system_configs 表为历史残留，
不再作为生效来源。GET 返回真实生效配置 + 对应 .env 变量名；PUT 一律拒绝，
引导到 .env 修改并重启后端。
"""
from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.deps import require_permission
from app.core.exceptions import AppError
from app.models import User
from app.schemas.system_config import SystemConfigOut

router = APIRouter(prefix="/system-configs", tags=["system-configs"])


def _mask_secret(value: str) -> str:
    """脱敏：首4尾4中间 ****；空串显示未配置；≤8 位整体打码。"""
    v = (value or "").strip()
    if not v:
        return "（未配置）"
    if len(v) <= 8:
        return "****"
    return f"{v[:4]}****{v[-4:]}"


def _effective_configs() -> list[dict]:
    """构造真实生效配置列表（含 .env 变量名），不读 DB。"""
    s = get_settings()
    return [
        {"key": "llm.provider", "value": s.llm_provider,
         "description": "大模型供应商（mock | openai）", "env_key": "LLM_PROVIDER"},
        {"key": "llm.api_key", "value": _mask_secret(s.llm_api_key),
         "description": "大模型 API Key（仅显示脱敏）", "env_key": "LLM_API_KEY"},
        {"key": "llm.base_url", "value": s.llm_base_url,
         "description": "大模型 API 地址", "env_key": "LLM_BASE_URL"},
        {"key": "llm.model", "value": s.llm_model,
         "description": "模型名称", "env_key": "LLM_MODEL"},
        {"key": "embedding.provider", "value": s.embedding_provider,
         "description": "向量模型供应商（mock | openai）", "env_key": "EMBEDDING_PROVIDER"},
        {"key": "embedding.api_key", "value": _mask_secret(s.embedding_api_key),
         "description": "向量模型 API Key（仅显示脱敏）", "env_key": "EMBEDDING_API_KEY"},
        {"key": "embedding.base_url", "value": s.embedding_base_url,
         "description": "向量模型 API 地址", "env_key": "EMBEDDING_BASE_URL"},
        {"key": "embedding.model", "value": s.embedding_model,
         "description": "向量模型名称", "env_key": "EMBEDDING_MODEL"},
        {"key": "embedding.dim", "value": str(s.embedding_dim),
         "description": "向量维度（部署级，变更需重建索引）", "env_key": "EMBEDDING_DIM"},
        {"key": "relevance.threshold", "value": str(s.relevance_threshold),
         "description": "相关度阈值（RRF 融合分量级 0.01-0.03）", "env_key": "RELEVANCE_THRESHOLD"},
        {"key": "chunk.size", "value": "500",
         "description": "新建知识库默认分块大小(tokens)，创建知识库时可单独设置",
         "env_key": None, "source": "default"},
        {"key": "chunk.overlap", "value": "50",
         "description": "新建知识库默认分块重叠(tokens)，创建知识库时可单独设置",
         "env_key": None, "source": "default"},
    ]


@router.get("", response_model=list[SystemConfigOut])
async def list_system_configs(
    _user: User = Depends(require_permission("system:config")),
):
    return _effective_configs()


@router.put("")
async def update_system_configs(
    _user: User = Depends(require_permission("system:config")),
):
    raise AppError(
        "配置为只读：请在 backend/.env 中修改对应变量并重启后端后生效",
        code="READONLY_CONFIG",
    )
