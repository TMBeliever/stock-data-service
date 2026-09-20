import http from "node:http";
import { URL } from "node:url";
import { WeixinBotManager } from "../manager/bot-manager.js";
import { logger } from "../util/logger.js";

/**
 * 快速解析 JWT Payload 提取用户信息
 */
function extractUserFromAuthHeader(authHeader?: string): { userId: string; username: string; token?: string } {
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return { userId: "web_guest", username: "guest" };
  }

  const token = authHeader.slice(7).trim();
  try {
    const parts = token.split(".");
    if (parts.length === 3) {
      const payloadStr = Buffer.from(parts[1], "base64url").toString("utf-8");
      const payload = JSON.parse(payloadStr);
      return {
        userId: String(payload.sub || payload.user_id || "web_user"),
        username: String(payload.username || payload.name || "user"),
        token,
      };
    }
  } catch (e) {
    logger.debug("解析 JWT Payload 失败:", e);
  }

  return { userId: "web_user", username: "user", token };
}

export function createHttpServer(manager: WeixinBotManager, port: number = 8095) {
  const server = http.createServer(async (req, res) => {
    // 允许跨域
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }

    const reqUrl = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
    const pathname = reqUrl.pathname;

    const sendJson = (statusCode: number, data: any) => {
      res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(data));
    };

    try {
      // 1. 获取微信登录二维码: GET /api/v1/weixin/qrcode
      if (req.method === "GET" && pathname === "/api/v1/weixin/qrcode") {
        const authUser = extractUserFromAuthHeader(req.headers.authorization);
        const result = await manager.requestQRCode(authUser);
        return sendJson(200, {
          status: "success",
          data: result,
        });
      }

      // 2. 轮询二维码扫码状态: GET /api/v1/weixin/status
      if (req.method === "GET" && pathname === "/api/v1/weixin/status") {
        const qrcode = reqUrl.searchParams.get("qrcode");
        if (!qrcode) {
          return sendJson(400, { status: "error", message: "缺少 qrcode 参数" });
        }
        const result = await manager.checkStatus(qrcode);
        return sendJson(200, {
          status: "success",
          data: result,
        });
      }

      // 3. 查询当前微信 Bot 运行与绑定信息: GET /api/v1/weixin/bot-info
      if (req.method === "GET" && pathname === "/api/v1/weixin/bot-info") {
        return sendJson(200, {
          status: "success",
          data: manager.getBotInfo(),
        });
      }

      // 4. 注销退出微信: POST /api/v1/weixin/logout
      if (req.method === "POST" && pathname === "/api/v1/weixin/logout") {
        await manager.logout();
        return sendJson(200, {
          status: "success",
          message: "微信已退出登录并解除绑定",
        });
      }

      // 5. 重置当前会话: POST /api/v1/weixin/reset-session
      if (req.method === "POST" && pathname === "/api/v1/weixin/reset-session") {
        manager.resetCurrentSession();
        return sendJson(200, {
          status: "success",
          message: "已重置当前对话上下文",
        });
      }

      // 健康探针
      if (pathname === "/health") {
        return sendJson(200, { status: "healthy", service: "weixin-bot" });
      }

      // 404 兜底
      return sendJson(404, { status: "error", message: `Not Found: ${pathname}` });
    } catch (err: any) {
      logger.error(`[HttpServer] 处理请求出错 [${req.method} ${pathname}]:`, err);
      return sendJson(500, { status: "error", message: err.message || "内部服务错误" });
    }
  });

  return server;
}
