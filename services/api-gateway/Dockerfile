FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# 安装基础系统工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 UV 极速包管理器
COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /bin/uv

# 复制微服务源码
COPY . .

# 极速安装依赖
RUN uv pip install --system -e .

# 暴露微服务网关端口
EXPOSE 8001

# 容器健康探针
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# 启动微服务网关
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8001"]
