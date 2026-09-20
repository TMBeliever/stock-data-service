import qrcodeTerminal from "qrcode-terminal";
import { apiGetFetch, apiPostFetch, DEFAULT_BASE_URL } from "../api/api.js";
import type { QRCodeResponse, StatusResponse } from "../api/types.js";
import { logger } from "../util/logger.js";

export interface LoginResult {
  token: string;
  accountId: string;
  baseUrl: string;
  userId?: string;
}

export class WeixinAuth {
  private baseUrl: string;
  private botType: string;

  constructor(options: { baseUrl?: string; botType?: string } = {}) {
    this.baseUrl = options.baseUrl || DEFAULT_BASE_URL;
    this.botType = options.botType || "3";
  }

  /**
   * Request a new login QR code.
   */
  async fetchQRCode(): Promise<QRCodeResponse> {
    const rawText = await apiPostFetch({
      baseUrl: this.baseUrl,
      endpoint: `ilink/bot/get_bot_qrcode?bot_type=${encodeURIComponent(this.botType)}`,
      body: JSON.stringify({ local_token_list: [] }),
      label: "fetchQRCode",
    });
    return JSON.parse(rawText) as QRCodeResponse;
  }

  /**
   * Check status of QR code once (with long-poll support).
   */
  async checkQRCodeStatus(qrcode: string, verifyCode?: string, timeoutMs: number = 25_000): Promise<StatusResponse> {
    let endpoint = `ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(qrcode)}`;
    if (verifyCode) {
      endpoint += `&verify_code=${encodeURIComponent(verifyCode)}`;
    }
    const rawText = await apiGetFetch({
      baseUrl: this.baseUrl,
      endpoint,
      timeoutMs,
      label: "checkQRCodeStatus",
    });
    return JSON.parse(rawText) as StatusResponse;
  }

  /**
   * Display QR code in terminal and print link.
   */
  displayQR(qrContent: string): void {
    console.log("\n================ 微信扫码登录 ================");
    qrcodeTerminal.generate(qrContent, { small: true });
    console.log("提示：请使用微信扫描上方二维码进行绑定授权。");
    console.log(`若终端二维码无法扫描，可手动打开链接：\n${qrContent}`);
    console.log("==============================================\n");
  }

  /**
   * Poll status until user scans and confirms, or timeout.
   */
  async waitForLogin(
    qrcode: string,
    options: {
      timeoutMs?: number;
      onScanned?: () => void;
      onNeedVerifyCode?: (prompt: string) => Promise<string>;
    } = {},
  ): Promise<LoginResult> {
    const timeoutMs = options.timeoutMs ?? 480_000;
    const deadline = Date.now() + timeoutMs;
    let currentBaseUrl = this.baseUrl;
    let pendingVerifyCode: string | undefined;
    let hasLoggedScanned = false;

    logger.info("等待扫码确认中...");

    while (Date.now() < deadline) {
      try {
        let endpoint = `ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(qrcode)}`;
        if (pendingVerifyCode) {
          endpoint += `&verify_code=${encodeURIComponent(pendingVerifyCode)}`;
        }

        const rawText = await apiGetFetch({
          baseUrl: currentBaseUrl,
          endpoint,
          timeoutMs: 35_000,
          label: "pollQRStatus",
        });

        const resp: StatusResponse = JSON.parse(rawText);

        switch (resp.status) {
          case "wait":
            // Keep waiting
            break;

          case "scaned":
            if (pendingVerifyCode) {
              pendingVerifyCode = undefined;
            }
            if (!hasLoggedScanned) {
              logger.info("已扫码，请在手机微信上点击【确认登录】...");
              hasLoggedScanned = true;
              options.onScanned?.();
            }
            break;

          case "need_verifycode": {
            const prompt = "手机微信提示输入配对码，请输入显示的验证数字：";
            if (options.onNeedVerifyCode) {
              pendingVerifyCode = await options.onNeedVerifyCode(prompt);
            } else {
              pendingVerifyCode = await this.readInputFromStdin(prompt);
            }
            continue;
          }

          case "scaned_but_redirect":
            if (resp.redirect_host) {
              currentBaseUrl = `https://${resp.redirect_host}`;
              logger.info(`机房重定向至: ${currentBaseUrl}`);
            }
            break;

          case "confirmed":
            if (!resp.bot_token || !resp.ilink_bot_id) {
              throw new Error("登录确认但未收到 bot_token 或 ilink_bot_id");
            }
            logger.info("✅ 微信登录成功！");
            return {
              token: resp.bot_token,
              accountId: resp.ilink_bot_id,
              baseUrl: resp.baseurl || currentBaseUrl,
              userId: resp.ilink_user_id,
            };

          case "expired":
            throw new Error("二维码已过期，请重新发起登录");

          case "verify_code_blocked":
            throw new Error("验证码多次输入错误，已被限制，请稍后再试");

          case "binded_redirect":
            throw new Error("此微信已绑定过该机器人，请直接使用已有凭证登录");
        }
      } catch (err: any) {
        if (err.name === "AbortError") {
          // Long poll timeout, continue loop
          continue;
        }
        if (err.message && (err.message.includes("已过期") || err.message.includes("绑定过"))) {
          throw err;
        }
        logger.debug("轮询状态异常（将自动重试）:", err);
      }

      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    throw new Error("扫码超时，请重新登录");
  }

  private readInputFromStdin(prompt: string): Promise<string> {
    process.stdout.write(`\n${prompt} `);
    return new Promise((resolve) => {
      process.stdin.resume();
      process.stdin.setEncoding("utf-8");
      const onData = (data: Buffer | string) => {
        const text = data.toString().trim();
        process.stdin.removeListener("data", onData);
        process.stdin.pause();
        resolve(text);
      };
      process.stdin.on("data", onData);
    });
  }
}
