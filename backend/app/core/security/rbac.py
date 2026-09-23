"""RBAC：角色→权限点映射（唯一来源）+ 权限判定工具。

权限点语法：`模块:动作`，如 kb:create、doc:vectorize。
通配：`*:*` 全权限；`kb:*` 匹配该模块所有动作。
"""
from collections.abc import Iterable


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*:*"},
    "editor": {
        "kb:create", "kb:read", "kb:update", "kb:delete",
        "doc:upload", "doc:read", "doc:delete", "doc:vectorize",
        "chat:use", "chat:history",
    },
    "viewer": {"kb:read", "doc:read", "chat:use", "chat:history"},
}

# 权限点全量清单（前端权限树 + 角色权限校验的唯一来源）。
# 注意：admin 用 *:* 通配覆盖全部，故其 permissions 列表里不含这些点。
PERMISSIONS_CATALOG: list[dict] = [
    {
        "module": "知识库",
        "key": "kb",
        "permissions": [
            {"key": "kb:read", "label": "查看"},
            {"key": "kb:create", "label": "创建"},
            {"key": "kb:update", "label": "编辑"},
            {"key": "kb:delete", "label": "删除"},
        ],
    },
    {
        "module": "文档",
        "key": "doc",
        "permissions": [
            {"key": "doc:upload", "label": "上传"},
            {"key": "doc:read", "label": "查看"},
            {"key": "doc:delete", "label": "删除"},
            {"key": "doc:vectorize", "label": "向量化"},
        ],
    },
    {
        "module": "对话",
        "key": "chat",
        "permissions": [
            {"key": "chat:use", "label": "发起对话"},
            {"key": "chat:history", "label": "查看历史"},
        ],
    },
    {
        "module": "系统管理",
        "key": "system",
        "permissions": [
            {"key": "user:manage", "label": "用户管理"},
            {"key": "role:manage", "label": "角色管理"},
            {"key": "system:config", "label": "系统设置"},
        ],
    },
]

BUILTIN_ROLES: tuple[str, ...] = ("admin", "editor", "viewer")
ALL_PERMISSION_KEYS: set[str] = {
    p["key"] for group in PERMISSIONS_CATALOG for p in group["permissions"]
}


def permission_match(required: str, granted: set[str]) -> bool:
    """判断 required 权限是否被 granted 集合覆盖（支持模块级通配）。"""
    if "*:*" in granted:
        return True
    if required in granted:
        return True
    ns = required.split(":", 1)[0]
    return f"{ns}:*" in granted


def collect_permissions(roles: Iterable) -> set[str]:
    """汇总用户的角色权限为一个集合。"""
    perms: set[str] = set()
    for role in roles:
        perms.update(role.permissions or [])
    return perms
