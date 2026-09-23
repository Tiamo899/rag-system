"""pytest 配置：确保 backend/ 在 sys.path，可导入 app 包。

测试统一走 mock 模型，避免真实调用外部 API（backend/.env 生产配置可能是 openai）。
环境变量优先级高于 .env 文件，这里强制覆盖。EMBEDDING_DIM 保持与 ES 索引一致。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBEDDING_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""
