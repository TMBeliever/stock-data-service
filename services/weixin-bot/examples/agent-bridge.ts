import fs from "node:fs";
import { WeixinBot } from "../src/index.js";

// 如果存在 .env 文件，自动载入环境变量 (Node.js 原生支持)
if (fs.existsSync(".env")) {
  try {
    process.loadEnvFile?.(".env");
  } catch (e) {
    // 忽略加载异常
  }
}

// NewAPI 基础配置
const NEWAPI_BASE_URL = process.env.NEWAPI_BASE_URL || "http://43.155.186.45:3000";
const NEWAPI_API_KEY = process.env.NEWAPI_API_KEY || "sk-W91gp63k2tmArgtL8wxIMoQaYj8CmFtumeF9T34xSpuIZj34";
let CURRENT_MODEL = process.env.NEWAPI_MODEL || "agt-gemini-3.8-flash";
const SYSTEM_PROMPT =
  process.env.SYSTEM_PROMPT || "你是微信个人智能助理，请用简洁、友好、自然的中文回复用户的消息。";

interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

// 维护每个微信用户的最近多轮对话上下文 (保存最近 10 条)
const userHistory = new Map<string, ChatMessage[]>();
const MAX_HISTORY_LENGTH = 10;

/**
 * 请求 NewAPI 兼容接口
 */
async function chatWithNewAPI(userId: string, userQuery: string): Promise<string> {
  // 获取或初始化该用户的历史会话
  let history = userHistory.get(userId);
  if (!history) {
    history = [{ role: "system", content: SYSTEM_PROMPT }];
    userHistory.set(userId, history);
  }

  // 追加当前用户消息
  history.push({ role: "user", content: userQuery });

  // 超过最大历史长度时，保持 system prompt 并截断旧消息
  if (history.length > MAX_HISTORY_LENGTH + 1) {
    history.splice(1, history.length - (MAX_HISTORY_LENGTH + 1));
  }

  const endpoint = `${NEWAPI_BASE_URL.replace(/\/+$/, "")}/v1/chat/completions`;

  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${NEWAPI_API_KEY.trim()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: CURRENT_MODEL,
      messages: history,
      temperature: 0.7,
    }),
  });

  const rawText = await response.text();
  let data: any;
  try {
    data = JSON.parse(rawText);
  } catch {
    throw new Error(`NewAPI 返回非 JSON 格式响应 (HTTP ${response.status}): ${rawText}`);
  }

  if (!response.ok || data.error) {
    const errorMsg = data.error?.message || `HTTP ${response.status}`;
    throw new Error(`NewAPI 请求失败 [${errorMsg}]`);
  }

  const replyContent = data.choices?.[0]?.message?.content;
  if (!replyContent) {
    throw new Error("模型未返回有效文本内容");
  }

  // 记录 AI 回复到历史
  history.push({ role: "assistant", content: replyContent });

  return replyContent;
}

async function main() {
  console.log("================ 微信 Agent 机器人 ================");
  console.log(`[配置] NewAPI 地址: ${NEWAPI_BASE_URL}`);
  console.log(`[配置] 当前模型:   ${CURRENT_MODEL}`);
  console.log("====================================================");

  const bot = new WeixinBot({
    storageDir: "./.data",
    botAgent: "NewAPIAgent/1.0",
  });

  bot.on("login", (session) => {
    console.log(`[事件] 微信登录成功！Bot ID: ${session.accountId}`);
  });

  bot.on("message", async (msg) => {
    if (!msg.text || msg.text.trim() === "") return;
    const text = msg.text.trim();

    console.log(`[收到微信消息] ${msg.sender}: "${text}"`);

    // 内置便捷指令：/clear 或 /reset 清空上下文记忆
    if (text === "/clear" || text === "/reset") {
      userHistory.delete(msg.sender);
      await msg.reply("🧹 已清空当前会话的历史记忆，开启全新对话。");
      return;
    }

    // 内置指令：/model 切换模型
    if (text.startsWith("/model")) {
      const parts = text.split(/\s+/);
      if (parts.length > 1) {
        CURRENT_MODEL = parts[1];
        await msg.reply(`⚙️ 当前模型已切换为: ${CURRENT_MODEL}`);
      } else {
        await msg.reply(`当前正在使用的模型: ${CURRENT_MODEL}\n你可以输入 /model <模型名> 进行切换。\n例如: /model gemini-2.5-flash`);
      }
      return;
    }

    try {
      // 1. 发送“正在输入”状态
      await msg.typing(1);

      // 2. 调用 NewAPI 大模型
      console.log(`[AI 思考中] 模型: ${CURRENT_MODEL}, 消息: "${text}"`);
      const answer = await chatWithNewAPI(msg.sender, text);
      console.log(`[AI 响应完毕] 回复: "${answer.slice(0, 60)}..."`);

      // 3. 将回答回传给微信用户
      await msg.reply(answer);
      console.log(`[发送回复完成] 已成功发送回微信会话`);
    } catch (err: any) {
      console.error("[错误] 大模型处理失败:", err);
      await msg.reply(`抱歉，调用 AI 服务时出错：${err.message || err}`);
    } finally {
      // 4. 取消“正在输入”状态
      await msg.typing(2);
    }
  });

  bot.on("error", (err) => {
    console.error("[微信连接错误]", err);
  });

  process.on("SIGINT", async () => {
    console.log("\n正在停止微信机器人...");
    await bot.stop();
    process.exit(0);
  });

  await bot.start();
}

main().catch(console.error);
