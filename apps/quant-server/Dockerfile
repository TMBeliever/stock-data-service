FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /bin/uv

# 复制 workspace 必要模块
COPY pyproject.toml .
COPY packages/quant-core packages/quant-core
COPY apps/quant-server apps/quant-server

# 安装依赖
RUN uv pip install --system -e packages/quant-core -e apps/quant-server

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
