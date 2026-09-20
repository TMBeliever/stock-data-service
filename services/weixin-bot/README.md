# Weixin Bot (脱离 OpenClaw 的轻量级微信 Bot SDK)

这是一个基于腾讯官方 **iLink 智联协议** (`https://ilinkai.weixin.qq.com`) 实现的轻量级微信个人号机器人 SDK。

本项目从 `@tencent-weixin/openclaw-weixin` 中抽离并解耦了底层网络长轮询与消息收发机制，**彻底移除了对 OpenClaw 框架的全部依赖**，你可以用原生 TypeScript / Node.js 把它作为独立微服务运行，并无缝对接任何自定义的 **AI Agent（Dify、FastGPT、LangChain、OpenAI / DeepSeek / 本地 Ollama 等）**。

---

## 🌟 核心特性

- **零 OpenClaw 绑定**：纯原生 Node.js + TypeScript 开发，包体极小，启动极快。
- **官方 iLink 通道**：走腾讯官方智联协议与二维码扫码授权，无需任何客户端内存注入、无需安装虚拟机中的微信、无封号顾虑。
- **开箱即用**：终端自动打印 ASCII 登录二维码，支持扫码确认、配对码输入，自动持久化凭证（下次启动免扫码）。
- **简单优雅的事件模型**：提供 `bot.on('message', async (msg) => msg.reply(...))` 的现代化 API，支持发送正在输入（typing）状态。
- **通用 Agent 适配器**：轻松桥接 Dify、FastGPT、LangChain 或自建 HTTP Webhook。

---

## 📁 目录结构

```
weixin-bot/
├── src/
│   ├── index.ts               # SDK 入口，导出核心类与方法
│   ├── client/
│   │   ├── bot.ts             # WeixinBot 控制器（事件管理、长轮询、自动断线重连）
│   │   └── auth.ts            # 扫码登录与验证码轮询
│   ├── api/
│   │   ├── api.ts             # iLink 官方接口封装 (getUpdates, sendMessage, typing 等)
│   │   └── types.ts           # 协议数据结构与消息类型定义
│   └── util/
│       ├── logger.ts          # 轻量控制台日志
│       └── storage.ts         # 本地会话与状态持久化 (.data/session.json)
├── examples/
│   ├── simple-bot.ts          # 基础扫码与复读机器人示例
│   └── agent-bridge.ts        # 挂接外部 Agent (Dify/大模型) 的实战示例
├── package.json
└── tsconfig.json
```

---

## 🚀 快速上手

### 1. 安装依赖

```bash
pnpm install
# 或者 npm install / yarn
```

### 2. 启动基础示例（扫码登录与自动回复）

```bash
pnpm run dev:simple
```

1. 终端将输出一个二维码（同时输出一个备用 Web 链接）；
2. 使用你的手机微信扫描该二维码并在手机上点击确认授权；
3. 授权成功后凭证会自动保存在本地 `.data/session.json`（下次启动无需再扫码）；
4. 向该微信号发送任意文字，机器人将自动响应。

### 3. 启动 Agent 桥接示例

```bash
pnpm run dev:agent
```

---

## 💡 对接你自己的 Agent

在 `examples/agent-bridge.ts` 中，只需在 `callMyAgent` 函数里调用你的 Agent API 即可：

```typescript
import { WeixinBot } from "./src/index.js";

const bot = new WeixinBot();

bot.on("message", async (msg) => {
  // 1. 发送“正在输入”状态（微信客户端会显示正在输入）
  await msg.typing(1);

  // 2. 调用你的任意 Agent (比如 Dify, OpenAI, 本地模型)
  const answer = await yourAgent.invoke(msg.text);

  // 3. 回复给用户
  await msg.reply(answer);
});

await bot.start();
```

---

## 🛠️ 构建与编译

若要编译为纯 JavaScript 在生产环境运行：

```bash
# 编译输出到 dist/ 目录
pnpm run build

# 生产环境运行
node dist/index.js
```
