# Quant Server (`apps/quant-server`)

基于 FastAPI 的全栈量化系统服务控制面与 API 网关。

---

## 核心接口能力

* **健康检查 (`GET /api/v1/health`)**：
  * 返回服务运行状态及与底层 `stock-data` 数据中台的连通性。
* **策略自描述元数据 (`GET /api/v1/strategies`)**：
  * 获取系统内置策略列表（如双均线、红利调仓）及其可配置参数 Schema，方便前端或 AI 自动生成配置表单。
* **在线回测调度 (`POST /api/v1/backtest/run`)**：
  * 接收回测请求参数（代码、策略、时间区间、初始资金、自定义参数）；
  * 调用底层数据和内核执行回测，返回完整的收益统计摘要与每日净值曲线。
* **跨域支持 (CORS)**：
  * 原生开启 CORS 中间件，允许前端 Vue 3（端口 5173）或移动端跨域直连调试。

---

## 本地启动与调试

```bash
# 1. 启动服务 (带热重载)
uv run uvicorn quant_server.main:app --host 0.0.0.0 --port 8080 --reload

# 2. 打开浏览器访问 Swagger API 交互文档
# http://localhost:8080/docs
```

## 容器构建

```bash
docker build -t quant-server:latest -f Dockerfile ../..
```
