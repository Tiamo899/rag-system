# Python 3.11 精简镜像（国内网络走 docker.1ms.run 加速器，还原官方源去掉前缀即可）
FROM docker.1ms.run/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# pip 国内镜像（网络正常可去掉 ARG 用默认 pypi）
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 先装依赖，利用 Docker 层缓存（改代码不重装依赖）
COPY requirements.txt .
RUN pip install --index-url ${PIP_INDEX_URL} -r requirements.txt

# 业务代码 + Alembic（注意：不 COPY .env，密钥只靠 compose 环境变量注入）
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
COPY scripts ./scripts

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
