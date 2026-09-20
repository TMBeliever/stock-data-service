import fs from "node:fs";
import { WeixinBotManager } from "./manager/bot-manager.js";
import { createHttpServer } from "./server/http-server.js";
import { logger } from "./util/logger.js";

// 如果存在 .env 文件，自动载入环境变量
if (fs.existsSync(".env")) {
  try {
    process.loadEnvFile?.(".env");
  } catch (e) {
    // 忽略加载异常
  }
}

const PORT = parseInt(process.env.PORT || "8095", 10);
const QUANT_AGENT_URL = process.env.QUANT_AGENT_URL || "http://127.0.0.1:8060";
const STORAGE_DIR = process.env.STORAGE_DIR || "./.data";

async function bootstrap() {
  console.log("==================================================");
  console.log("🚀 微信量化智能助理服务 (Weixin Bot Service)");
  console.log(`📡 HTTP 服务端口:    ${PORT}`);
  console.log(`🤖 QuantAgent 地址:  ${QUANT_AGENT_URL}`);
  console.log(`💾 数据持久化目录:  ${STORAGE_DIR}`);
  console.log("==================================================");

  const manager = new WeixinBotManager({
    storageDir: STORAGE_DIR,
    quantAgentUrl: QUANT_AGENT_URL,
  });

  // 1. 如果此前已有持久化凭证，自动恢复微信连接
  await manager.autoResume();

  // 2. 启动 HTTP 管理服务 (提供扫码、状态查询、会话管理等 Web 接口)
  const server = createHttpServer(manager, PORT);

  server.listen(PORT, "0.0.0.0", () => {
    logger.info(`微信 Web 管理服务已就绪: http://0.0.0.0:${PORT}`);
  });

  const shutdown = async () => {
    logger.info("正在安全退出微信服务...");
    server.close();
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

bootstrap().catch((err) => {
  logger.error("微信服务启动失败:", err);
  process.exit(1);
});
