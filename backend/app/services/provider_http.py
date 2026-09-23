"""模型 Provider HTTP 公共工具：统一错误分类与上报。"""
import logging

import httpx

from app.core.exceptions import ProviderError

logger = logging.getLogger(__name__)


def raise_provider_error(provider: str, resp: httpx.Response) -> None:
    """按上游 HTTP 状态分类抛 ProviderError。provider 用于文案（如 "LLM"/"Embedding"）。"""
    status = resp.status_code
    try:
        body = resp.json()
        detail = body.get("error", {}).get("message") or resp.text[:300]
    except Exception:  # noqa: BLE001
        detail = resp.text[:300]

    if status in (401, 403):
        raise ProviderError(
            f"{provider} 服务认证失败（HTTP {status}）：API Key 无效或已过期，"
            "请在 backend/.env 检查对应 API Key",
            code="PROVIDER_AUTH_ERROR", provider_status=status, detail=detail,
        )
    if status == 429:
        raise ProviderError(
            f"{provider} 服务限流（HTTP 429），请稍后重试",
            code="PROVIDER_RATE_LIMITED", provider_status=status, detail=detail,
        )
    if status >= 500:
        raise ProviderError(
            f"{provider} 服务暂时不可用（HTTP {status}）",
            code="PROVIDER_UNAVAILABLE", provider_status=status, detail=detail,
        )
    raise ProviderError(
        f"{provider} 服务请求失败（HTTP {status}）：{detail}",
        code="PROVIDER_ERROR", provider_status=status, detail=detail,
    )


def wrap_network_error(provider: str, exc: Exception) -> ProviderError:
    """把 httpx.HTTPError（连接失败/超时/DNS 等）转成可读错误。"""
    return ProviderError(
        f"无法连接 {provider} 服务：{exc}",
        code="PROVIDER_NETWORK_ERROR", detail=str(exc),
    )
