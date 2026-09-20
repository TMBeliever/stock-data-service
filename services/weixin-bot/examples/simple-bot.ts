import { WeixinBot } from "../src/index.js";

async function main() {
  const bot = new WeixinBot({
    storageDir: "./.data",
    botAgent: "SimpleBot/1.0",
  });

  // 监听登录事件
  bot.on("login", (session) => {
    console.log(`[事件] 登录成功，Bot ID: ${session.accountId}`);
  });

  // 监听收到的微信消息
  bot.on("message", async (msg) => {
    console.log(`[收到消息] 来自 ${msg.sender}: "${msg.text}"`);

    // 提示用户正在输入/思考
    await msg.typing(1);

    if (msg.text === "/ping") {
      await msg.reply("pong! 机器人运行正常。");
    } else if (msg.text.startsWith("/echo ")) {
      const content = msg.text.replace("/echo ", "");
      await msg.reply(`复读: ${content}`);
    } else {
      await msg.reply(`你好！已收到你的消息: "${msg.text}"\n你可以输入 /ping 或 /echo <内容> 进行测试。`);
    }
  });

  // 监听异常
  bot.on("error", (err) => {
    console.error("[错误]", err);
  });

  // 捕获退出信号优雅退出
  process.on("SIGINT", async () => {
    console.log("\n正在停止机器人...");
    await bot.stop();
    process.exit(0);
  });

  // 启动机器人（如果本地没有 session.json 则在终端显示扫码）
  await bot.start();
}

main().catch((err) => {
  console.error("启动失败:", err);
});
