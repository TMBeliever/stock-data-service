FROM python:3.11-slim

WORKDIR /app

# 安装 curl 供容器健康检查使用
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 拷贝依赖描述并安装
COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache -e .

COPY src/ ./src/
ENV PYTHONPATH=/app/src

EXPOSE 8040

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8040/health || exit 1

CMD ["uvicorn", "asset_server.main:app", "--host", "0.0.0.0", "--port", "8040"]
