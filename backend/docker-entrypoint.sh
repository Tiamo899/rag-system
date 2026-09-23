#!/bin/sh
set -e
# 迁移在 uvicorn 启动前执行；PG 就绪由 compose depends_on(service_healthy) 保证
alembic upgrade head
exec "$@"
