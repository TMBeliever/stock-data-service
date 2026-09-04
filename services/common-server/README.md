# Common Server (通用业务与用户鉴权服务)

量化交易系统的通用微服务，负责用户注册、登录、JWT 鉴权拦截、VIP 身份标识与权限守卫。

## 默认配置
- **服务端口**：`8090`
- **数据库**：本地异步 SQLite (`data/common.db`)
- **API 基础路径**：`/api/v1/auth`

## 快速运行
```bash
# 在工作区根目录下执行
uv run uvicorn common_server.main:app --host 0.0.0.0 --port 8090 --reload
```
