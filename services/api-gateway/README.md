# Quant System API Gateway (统一 API 业务网关)

基于 FastAPI + 异步反向代理打造的全系统统一业务网关中枢。

## 核心职责
1. **统一鉴权与身份识别 (Auth Centralization)**：
   - 外部请求携带 JWT，网关在入口统一验签。
   - 剥除外部客户端传入的不可信 `X-User-*` 请求头，注入受信任的 `X-User-Id`, `X-User-Name`, `X-User-Role`。
   - 保护下游服务，下游微服务只读安全请求头，无需各自实现 JWT 验签。
2. **动态路由转发 (Dynamic Routing)**：
   - `/api/v1/auth/*` -> `common-server` (8090)
   - `/api/v1/user/*` -> `common-server` (8090)
   - `/api/v1/asset/*` -> `asset-server` (8050)
   - `/api/v1/agent/*` -> `quant-agent` (8060, 支持 SSE 流式免缓冲打字机)
   - `/api/v1/ai/*`、`/v1/*`、`/messages` -> `ai-core` (8070)
   - `/stock/*` -> `stock-data` (8000)
   - `/ws/*` -> `stock-data` (8000, WebSocket 全双工通道透传)
   - `/mcp/*` -> `mcp-gateway` (8050)
   - `/api/v1/weixin/*` -> `weixin-bot` (8095)
   - 兜底 `/api/v1/*` -> `quant-server` (8080)
3. **全链路链路追踪 (Traceability)**：
   - 自动生成或透传 `X-Request-Id`。
4. **统一跨域治理 (CORS)**：
   - 全局拦截并处理 OPTIONS 预检请求与 CORS Headers。
