FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    nodejs \
    npm \
    && (which node || ln -s $(which nodejs) /usr/local/bin/node 2>/dev/null || true) \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /bin/uv

COPY . .

RUN uv pip install --system -e .

EXPOSE 8070

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8070/health || exit 1

CMD ["uvicorn", "ai_core.service:app", "--host", "0.0.0.0", "--port", "8070"]
