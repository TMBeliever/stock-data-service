import { EventEmitter } from "node:events";
import {
  getUpdates,
  sendMessage,
  sendTyping,
  notifyStop,
  DEFAULT_BASE_URL,
} from "../api/api.js";
import { MessageItemType, MessageState, MessageType } from "../api/types.js";
import type { WeixinMessage } from "../api/types.js";
import { SessionStorage } from "../util/storage.js";
import type { BotSession } from "../util/storage.js";
import { WeixinAuth } from "./auth.js";
import { logger } from "../util/logger.js";

export interface BotOptions {
  storageDir?: string;
  baseUrl?: string;
  botAgent?: string;
  autoSaveSession?: boolean;
}

export class BotMessage {
  public readonly sender: string;
  public readonly text: string;
  public readonly raw: WeixinMessage;
  public readonly contextToken?: string;
  private readonly bot: WeixinBot;

  constructor(bot: WeixinBot, raw: WeixinMessage) {
    this.bot = bot;
    this.raw = raw;
    this.sender = raw.from_user_id || "";
    this.contextToken = raw.context_token;

    // Extract text content
    let extractedText = "";
    if (raw.item_list && raw.item_list.length > 0) {
      for (const item of raw.item_list) {
        if (item.type === MessageItemType.TEXT && item.text_item?.text) {
          extractedText += item.text_item.text;
        } else if (item.type === MessageItemType.VOICE && item.voice_item?.text) {
          extractedText += item.voice_item.text;
        }
      }
    }
    this.text = extractedText;
  }

  /**
   * Reply to this message.
   */
  async reply(content: string): Promise<void> {
    await this.bot.sendMessage(this.sender, content, this.contextToken);
  }

  /**
   * Send typing status (1: typing, 2: cancel typing).
   */
  async typing(status: number = 1): Promise<void> {
    await this.bot.sendTyping(this.sender, status);
  }
}

export class WeixinBot extends EventEmitter {
  private options: Required<BotOptions>;
  private storage: SessionStorage;
  private auth: WeixinAuth;
  private session: BotSession | null = null;
  private running: boolean = false;
  private abortController: AbortController | null = null;

  constructor(options: BotOptions = {}) {
    super();
    this.options = {
      storageDir: options.storageDir || "./.data",
      baseUrl: options.baseUrl || DEFAULT_BASE_URL,
      botAgent: options.botAgent || "WeixinBot/1.0.0",
      autoSaveSession: options.autoSaveSession ?? true,
    };
    this.storage = new SessionStorage(this.options.storageDir);
    this.auth = new WeixinAuth({ baseUrl: this.options.baseUrl });
  }

  /**
   * Get current session.
   */
  getSession(): BotSession | null {
    return this.session;
  }

  /**
   * Login using cached session or initiate QR scan.
   */
  async login(options: { force?: boolean } = {}): Promise<BotSession> {
    if (!options.force) {
      const saved = this.storage.load();
      if (saved && saved.token && saved.accountId) {
        logger.info(`载入本地凭证: accountId=${saved.accountId}`);
        this.session = saved;
        this.emit("login", saved);
        return saved;
      }
    }

    // Need new login
    logger.info("获取微信登录二维码...");
    const qr = await this.auth.fetchQRCode();
    this.auth.displayQR(qr.qrcode_img_content);

    const loginRes = await this.auth.waitForLogin(qr.qrcode);
    const session: BotSession = {
      token: loginRes.token,
      accountId: loginRes.accountId,
      baseUrl: loginRes.baseUrl || this.options.baseUrl,
      userId: loginRes.userId,
      savedAt: Date.now(),
    };

    if (this.options.autoSaveSession) {
      this.storage.save(session);
    }

    this.session = session;
    this.emit("login", session);
    return session;
  }

  /**
   * Start long-polling message loop.
   */
  async start(): Promise<void> {
    if (!this.session) {
      await this.login();
    }
    if (!this.session) {
      throw new Error("无法启动：未找到有效会话凭证");
    }

    this.running = true;
    this.abortController = new AbortController();
    logger.info("微信消息监听已启动...");

    let updatesBuf = this.session.getUpdatesBuf || "";

    while (this.running) {
      if (!this.session) {
        break;
      }
      try {
        const resp = await getUpdates({
          baseUrl: this.session.baseUrl,
          token: this.session.token,
          getUpdatesBuf: updatesBuf,
          botAgent: this.options.botAgent,
          abortSignal: this.abortController?.signal,
        });

        const isApiError =
          (resp.ret !== undefined && resp.ret !== 0) ||
          (resp.errcode !== undefined && resp.errcode !== 0);

        if (!isApiError) {
          if (resp.get_updates_buf) {
            updatesBuf = resp.get_updates_buf;
            this.storage.saveUpdatesBuf(updatesBuf);
          }

          if (resp.msgs && resp.msgs.length > 0) {
            console.log(`\n[微信推送] 收到 ${resp.msgs.length} 条消息:`);
            for (const rawMsg of resp.msgs) {
              console.log(` -> 发送者: ${rawMsg.from_user_id || "(空)"}, 类型: ${rawMsg.message_type}, 条目数: ${rawMsg.item_list?.length ?? 0}`);
              // 仅过滤掉来自机器人账号自身 ID 的出站回显
              if (rawMsg.from_user_id === this.session.accountId) {
                console.log(`    (跳过机器人自身回显)`);
                continue;
              }

              const msg = new BotMessage(this, rawMsg);
              console.log(`    提取到文本内容: "${msg.text}"`);
              this.emit("message", msg);
            }
          }
        } else if (resp.errcode === -14) {
          logger.warn("微信登录 Session 已失效 (errcode -14)，需要重新扫码登录");
          this.storage.clear();
          this.session = null;
          await this.login({ force: true });
        }
      } catch (err: any) {
        if (!this.running || err.name === "AbortError") {
          break;
        }
        logger.error("消息轮询异常 (将在 3 秒后重试):", err.message || err);
        this.emit("error", err);
        await new Promise((r) => setTimeout(r, 3000));
      }
    }
  }

  /**
   * Send text message to user.
   */
  async sendMessage(toUserId: string, content: string, contextToken?: string): Promise<void> {
    if (!this.session) {
      throw new Error("未登录，无法发送消息");
    }

    const clientId = `bot_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

    await sendMessage({
      baseUrl: this.session.baseUrl,
      token: this.session.token,
      botAgent: this.options.botAgent,
      body: {
        msg: {
          from_user_id: "",
          to_user_id: toUserId,
          client_id: clientId,
          context_token: contextToken,
          message_type: MessageType.BOT,
          message_state: MessageState.FINISH,
          item_list: [
            {
              type: MessageItemType.TEXT,
              text_item: { text: content },
            },
          ],
        },
      },
    });
  }

  /**
   * Send typing status.
   */
  async sendTyping(toUserId: string, status: number = 1): Promise<void> {
    if (!this.session) return;
    try {
      await sendTyping({
        baseUrl: this.session.baseUrl,
        token: this.session.token,
        userId: toUserId,
        status,
        botAgent: this.options.botAgent,
      });
    } catch (e) {
      logger.debug("sendTyping failed:", e);
    }
  }

  /**
   * Stop bot gracefully.
   */
  async stop(): Promise<void> {
    this.running = false;
    if (this.abortController) {
      this.abortController.abort();
    }
    if (this.session) {
      await notifyStop({
        baseUrl: this.session.baseUrl,
        token: this.session.token,
        botAgent: this.options.botAgent,
      });
    }
    logger.info("微信机器人已停止。");
    this.emit("stop");
  }
}
