FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    WORKSPACE_ROOT=/app

# 安装基础系统工具、Git 与 Docker 客户端 CLI (支持 Docker-outside-of-Docker)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# 安装 UV 极速包管理器
COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /bin/uv

# 复制 workspace 必要模块与配置
COPY pyproject.toml .
COPY packages/ai-core packages/ai-core
COPY packages/agent-core packages/agent-core
COPY packages/stock-data packages/stock-data
COPY services/quant-agent services/quant-agent

# 安装所有关联依赖
RUN uv pip install --system \
    -e packages/ai-core \
    -e packages/agent-core \
    -e packages/stock-data \
    -e services/quant-agent

# 持久化存储挂载点 (存放 projects.json 会话树与上传工程)
VOLUME ["/app/data"]

EXPOSE 8060

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8060/health || exit 1

CMD ["uvicorn", "quant_agent.main:app", "--host", "0.0.0.0", "--port", "8060"]
