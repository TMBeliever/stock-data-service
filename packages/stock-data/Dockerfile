FROM python:3.12-slim

# 设置工作目录与 Python 运行环境变量
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

# 安装 UV 极速包管理器 (固定生产版本保障构建可重现)
COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /bin/uv

# 复制项目代码 (受 .dockerignore 保护仅包含轻量源码)
COPY . .

# 极速安装依赖与项目
RUN uv pip install --system -e .

# 声明 50GB 持久化存储挂载卷
VOLUME ["/app/data"]

# 开放 FastAPI 默认服务端口
EXPOSE 8000

# 容器健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/system/storage || exit 1

# 启动服务
CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000"]
