import fs from "node:fs";
import path from "node:path";
import QRCode from "qrcode";
import { WeixinBot } from "../client/bot.js";
import { WeixinAuth } from "../client/auth.js";
import { QuantAgentBridge } from "../agent/quant-bridge.js";
import { logger } from "../util/logger.js";
import type { BotSession } from "../util/storage.js";

export interface BoundUserInfo {
  userId: string;
  username: string;
  token?: string;
  boundAt: number;
}

export interface PendingQRCode {
  qrcode: string;
  imgContent: string;
  createdAt: number;
  user: {
    userId: string;
    username: string;
    token?: string;
  };
}

export class WeixinBotManager {
  private storageDir: string;
  private bindingFile: string;
  private auth: WeixinAuth;
  private bot: WeixinBot | null = null;
  private bridge: QuantAgentBridge;
  private boundUser: BoundUserInfo | null = null;
  private pendingQRCodes = new Map<string, PendingQRCode>();
  private isBotRunning: boolean = false;

  constructor(options: { storageDir?: string; quantAgentUrl?: string } = {}) {
    this.storageDir = options.storageDir || "./.data";
    if (!fs.existsSync(this.storageDir)) {
      fs.mkdirSync(this.storageDir, { recursive: true });
    }
    this.bindingFile = path.join(this.storageDir, "user_binding.json");
    this.auth = new WeixinAuth();

    // 初始化 QuantAgent 桥接器
    this.bridge = new QuantAgentBridge({
      quantAgentUrl: options.quantAgentUrl,
      getUserToken: () => this.boundUser?.token || null,
      getBoundUserId: () => this.boundUser?.userId || null,
    });

    this.loadBinding();
  }

  /**
   * 载入本地保存的用户绑定信息
   */
  private loadBinding(): void {
    if (fs.existsSync(this.bindingFile)) {
      try {
        const raw = fs.readFileSync(this.bindingFile, "utf-8");
        this.boundUser = JSON.parse(raw);
        logger.info(`已载入微信绑定的平台用户: [${this.boundUser?.username}] (ID: ${this.boundUser?.userId})`);
      } catch (e) {
        logger.warn("读取用户绑定文件失败:", e);
      }
    }
  }

  /**
   * 保存当前绑定的用户信息
   */
  private saveBinding(user: BoundUserInfo): void {
    try {
      fs.writeFileSync(this.bindingFile, JSON.stringify(user, null, 2), "utf-8");
      this.boundUser = user;
    } catch (e) {
      logger.error("保存用户绑定信息失败:", e);
    }
  }

  /**
   * 清除用户绑定信息
   */
  private clearBinding(): void {
    this.boundUser = null;
    if (fs.existsSync(this.bindingFile)) {
      try {
        fs.unlinkSync(this.bindingFile);
      } catch (e) {
        logger.warn("删除绑定文件失败:", e);
      }
    }
  }

  /**
   * 获取当前微信 Bot 运行状态与绑定信息
   */
  public getBotInfo() {
    const session = this.bot?.getSession();
    return {
      online: this.isBotRunning,
      accountId: session?.accountId || null,
      userId: session?.userId || null,
      savedAt: session?.savedAt || null,
      boundUser: this.boundUser
        ? {
            userId: this.boundUser.userId,
            username: this.boundUser.username,
            boundAt: this.boundUser.boundAt,
          }
        : null,
    };
  }

  /**
   * Web 用户发起请求：获取专属登录二维码
   */
  public async requestQRCode(user: { userId: string; username: string; token?: string }) {
    // 已经在线时提示
    if (this.isBotRunning && this.bot?.getSession()) {
      return {
        alreadyOnline: true,
        botInfo: this.getBotInfo(),
      };
    }

    const qr = await this.auth.fetchQRCode();
    let qrDataUrl = "";
    try {
      qrDataUrl = await QRCode.toDataURL(qr.qrcode_img_content, {
        width: 260,
        margin: 2,
        color: {
          dark: "#000000",
          light: "#ffffff",
        },
      });
    } catch (e) {
      logger.warn("生成二维码 DataURL 异常:", e);
    }

    const pending: PendingQRCode = {
      qrcode: qr.qrcode,
      imgContent: qr.qrcode_img_content,
      createdAt: Date.now(),
      user,
    };

    this.pendingQRCodes.set(qr.qrcode, pending);

    // 清理 10 分钟前的过期二维码请求
    const expireTime = Date.now() - 10 * 60 * 1000;
    for (const [code, item] of this.pendingQRCodes.entries()) {
      if (item.createdAt < expireTime) {
        this.pendingQRCodes.delete(code);
      }
    }

    return {
      alreadyOnline: false,
      qrcode: qr.qrcode,
      qrcodeImgContent: qr.qrcode_img_content,
      qrDataUrl,
    };
  }

  /**
   * Web 端轮询扫码状态
   */
  public async checkStatus(qrcode: string) {
    const pending = this.pendingQRCodes.get(qrcode);
    const resp = await this.auth.checkQRCodeStatus(qrcode);

    if (resp.status === "confirmed") {
      if (!resp.bot_token || !resp.ilink_bot_id) {
        throw new Error("微信确认登录，但未返回凭据");
      }

      const session: BotSession = {
        token: resp.bot_token,
        accountId: resp.ilink_bot_id,
        baseUrl: resp.baseurl || "https://ilinkai.weixin.qq.com",
        userId: resp.ilink_user_id,
        savedAt: Date.now(),
      };

      // 绑定 Web 用户身份
      if (pending) {
        this.saveBinding({
          userId: pending.user.userId,
          username: pending.user.username,
          token: pending.user.token,
          boundAt: Date.now(),
        });
        this.pendingQRCodes.delete(qrcode);
      }

      // 启动 Bot 实例
      await this.startBot(session);

      return {
        status: "confirmed",
        botInfo: this.getBotInfo(),
      };
    }

    return {
      status: resp.status,
    };
  }

  /**
   * 启动 Bot 消息监听
   */
  public async startBot(session?: BotSession): Promise<void> {
    if (this.isBotRunning && this.bot) {
      return;
    }

    this.bot = new WeixinBot({
      storageDir: this.storageDir,
      autoSaveSession: true,
    });

    this.bot.on("message", async (msg) => {
      await this.bridge.handleMessage(msg);
    });

    this.bot.on("error", (err) => {
      logger.error("[WeixinBotManager] Bot 运行异常:", err);
    });

    this.bot.on("stop", () => {
      this.isBotRunning = false;
      logger.info("[WeixinBotManager] Bot 已停止运行");
    });

    // 若传入了 session，先在本地保存以便 bot.start() 恢复
    if (session) {
      const sessionFile = path.join(this.storageDir, "session.json");
      fs.writeFileSync(sessionFile, JSON.stringify(session, null, 2), "utf-8");
    }

    // 后台异步启动消息长轮询
    this.isBotRunning = true;
    this.bot.start().catch((err) => {
      logger.error("[WeixinBotManager] Bot 启动失败:", err);
      this.isBotRunning = false;
    });

    logger.info(`[WeixinBotManager] 微信 Bot 实例已成功启动，已绑定用户: ${this.boundUser?.username || "未知"}`);
  }

  /**
   * 重置当前用户会话
   */
  public resetCurrentSession(): void {
    if (this.boundUser?.userId) {
      this.bridge.resetSession(this.boundUser.userId);
    }
  }

  /**
   * 注销退出当前微信登录
   */
  public async logout(): Promise<void> {
    if (this.bot) {
      try {
        await this.bot.stop();
      } catch (e) {
        logger.warn("停止微信 Bot 实例时发生警告:", e);
      }
      this.bot = null;
    }
    this.isBotRunning = false;
    this.clearBinding();

    // 清理 session 文件
    const sessionFile = path.join(this.storageDir, "session.json");
    if (fs.existsSync(sessionFile)) {
      try {
        fs.unlinkSync(sessionFile);
      } catch (e) {
        // 忽略
      }
    }
    logger.info("[WeixinBotManager] 微信登录已注销并清理本地凭证");
  }

  /**
   * 服务启动时若本地存在持久化 Session，自动恢复运行
   */
  public async autoResume(): Promise<void> {
    const sessionFile = path.join(this.storageDir, "session.json");
    if (fs.existsSync(sessionFile)) {
      try {
        const raw = fs.readFileSync(sessionFile, "utf-8");
        const session: BotSession = JSON.parse(raw);
        if (session.token && session.accountId) {
          logger.info(`[WeixinBotManager] 检测到持久化微信凭证 (Account: ${session.accountId})，正在自动恢复连接...`);
          await this.startBot(session);
        }
      } catch (err) {
        logger.warn("[WeixinBotManager] 恢复持久化会话失败:", err);
      }
    }
  }
}
