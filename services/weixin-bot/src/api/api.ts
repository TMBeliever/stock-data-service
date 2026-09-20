import crypto from "node:crypto";
import { logger } from "../util/logger.js";
import type {
  BaseInfo,
  GetUpdatesReq,
  GetUpdatesResp,
  SendMessageReq,
  SendMessageResp,
  SendTypingReq,
} from "./types.js";

export const DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com";
export const ILINK_APP_ID = "bot";
// 对应 2.4.9: (2 << 16) | (4 << 8) | 9 = 132105
export const ILINK_APP_CLIENT_VERSION = 132105;
export const DEFAULT_BOT_AGENT = "OpenClaw";

export function buildBaseInfo(botAgent: string = DEFAULT_BOT_AGENT): BaseInfo {
  return {
    channel_version: "2.4.9",
    bot_agent: botAgent,
  };
}

function ensureTrailingSlash(url: string): string {
  return url.endsWith("/") ? url : `${url}/`;
}

/** Generate random X-WECHAT-UIN header: random uint32 -> decimal string -> base64. */
function randomWechatUin(): string {
  const uint32 = crypto.randomBytes(4).readUInt32BE(0);
  return Buffer.from(String(uint32), "utf-8").toString("base64");
}

function buildHeaders(token?: string): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    AuthorizationType: "ilink_bot_token",
    "X-WECHAT-UIN": randomWechatUin(),
    "iLink-App-Id": ILINK_APP_ID,
    "iLink-App-ClientVersion": String(ILINK_APP_CLIENT_VERSION),
  };
  if (token?.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return headers;
}

const LOSSLESS_ID_FIELDS = new Set(["message_id", "msg_id", "svr_id"]);

/**
 * Losslessly parse uint64 identifiers in JSON without float precision loss.
 */
export function parseWeixinApiJson<T>(rawText: string): T {
  let output = "";
  let index = 0;
  while (index < rawText.length) {
    if (rawText[index] !== '"') {
      output += rawText[index++];
      continue;
    }

    const stringStart = index;
    index++;
    let escaped = false;
    while (index < rawText.length) {
      const char = rawText[index++];
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === '"') {
        break;
      }
    }
    const stringToken = rawText.slice(stringStart, index);
    output += stringToken;

    let cursor = index;
    while (/\s/.test(rawText[cursor] ?? "")) cursor++;
    if (rawText[cursor] !== ":") continue;

    let key: unknown;
    try {
      key = JSON.parse(stringToken);
    } catch {
      continue;
    }
    if (typeof key !== "string" || !LOSSLESS_ID_FIELDS.has(key)) continue;

    output += rawText.slice(index, cursor + 1);
    cursor++;
    while (/\s/.test(rawText[cursor] ?? "")) {
      output += rawText[cursor++];
    }
    const numberStart = cursor;
    if (rawText[cursor] === "-") cursor++;
    while (/\d/.test(rawText[cursor] ?? "")) cursor++;
    if (cursor > numberStart && !(cursor === numberStart + 1 && rawText[numberStart] === "-")) {
      output += `"${rawText.slice(numberStart, cursor)}"`;
      index = cursor;
    } else {
      index = numberStart;
    }
  }
  return JSON.parse(output) as T;
}

export async function apiGetFetch(params: {
  baseUrl: string;
  endpoint: string;
  token?: string;
  timeoutMs?: number;
  label?: string;
}): Promise<string> {
  const base = ensureTrailingSlash(params.baseUrl);
  const url = new URL(params.endpoint, base);
  const headers = buildHeaders(params.token);

  const controller = params.timeoutMs ? new AbortController() : undefined;
  const timeoutId =
    controller && params.timeoutMs
      ? setTimeout(() => controller.abort(), params.timeoutMs)
      : undefined;

  try {
    const res = await fetch(url.toString(), {
      method: "GET",
      headers,
      signal: controller?.signal,
    });
    if (timeoutId) clearTimeout(timeoutId);

    const text = await res.text();
    if (!res.ok) {
      throw new Error(`[${params.label || "GET"}] HTTP ${res.status}: ${text}`);
    }
    return text;
  } catch (err) {
    if (timeoutId) clearTimeout(timeoutId);
    throw err;
  }
}

export async function apiPostFetch(params: {
  baseUrl: string;
  endpoint: string;
  body: string;
  token?: string;
  timeoutMs?: number;
  label?: string;
  abortSignal?: AbortSignal;
}): Promise<string> {
  const base = ensureTrailingSlash(params.baseUrl);
  const url = new URL(params.endpoint, base);
  const headers = buildHeaders(params.token);

  const controller = params.timeoutMs ? new AbortController() : undefined;
  const timeoutId =
    controller && params.timeoutMs
      ? setTimeout(() => controller.abort(), params.timeoutMs)
      : undefined;

  let effectiveSignal: AbortSignal | undefined = controller?.signal;
  if (params.abortSignal) {
    if (controller) {
      params.abortSignal.addEventListener("abort", () => controller.abort(), { once: true });
    } else {
      effectiveSignal = params.abortSignal;
    }
  }

  try {
    const res = await fetch(url.toString(), {
      method: "POST",
      headers,
      body: params.body,
      signal: effectiveSignal,
    });
    if (timeoutId) clearTimeout(timeoutId);

    const text = await res.text();
    if (!res.ok) {
      throw new Error(`[${params.label || "POST"}] HTTP ${res.status}: ${text}`);
    }
    return text;
  } catch (err) {
    if (timeoutId) clearTimeout(timeoutId);
    throw err;
  }
}

/**
 * Long-poll getUpdates from Weixin server.
 */
export async function getUpdates(params: {
  baseUrl: string;
  token: string;
  getUpdatesBuf?: string;
  timeoutMs?: number;
  botAgent?: string;
  abortSignal?: AbortSignal;
}): Promise<GetUpdatesResp> {
  const timeout = params.timeoutMs ?? 35_000;
  try {
    const rawText = await apiPostFetch({
      baseUrl: params.baseUrl,
      endpoint: "ilink/bot/getupdates",
      body: JSON.stringify({
        get_updates_buf: params.getUpdatesBuf ?? "",
        base_info: buildBaseInfo(params.botAgent),
      }),
      token: params.token,
      timeoutMs: timeout,
      label: "getUpdates",
      abortSignal: params.abortSignal,
    });
    return parseWeixinApiJson<GetUpdatesResp>(rawText);
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      // Normal long-poll timeout or user cancel
      return { ret: 0, msgs: [], get_updates_buf: params.getUpdatesBuf };
    }
    throw err;
  }
}

/**
 * Send message to Weixin user.
 */
export async function sendMessage(params: {
  baseUrl: string;
  token: string;
  body: SendMessageReq;
  botAgent?: string;
}): Promise<SendMessageResp> {
  const rawText = await apiPostFetch({
    baseUrl: params.baseUrl,
    endpoint: "ilink/bot/sendmessage",
    body: JSON.stringify({
      ...params.body,
      base_info: buildBaseInfo(params.botAgent),
    }),
    token: params.token,
    timeoutMs: 15_000,
    label: "sendMessage",
  });
  const resp = parseWeixinApiJson<SendMessageResp>(rawText);
  if (resp.ret && resp.ret !== 0) {
    throw new Error(`sendMessage failed ret=${resp.ret} errmsg=${resp.errmsg ?? ""}`);
  }
  return resp;
}

/**
 * Send typing status to Weixin user.
 */
export async function sendTyping(params: {
  baseUrl: string;
  token: string;
  userId: string;
  typingTicket?: string;
  status?: number;
  botAgent?: string;
}): Promise<void> {
  await apiPostFetch({
    baseUrl: params.baseUrl,
    endpoint: "ilink/bot/sendtyping",
    body: JSON.stringify({
      ilink_user_id: params.userId,
      typing_ticket: params.typingTicket,
      status: params.status ?? 1,
      base_info: buildBaseInfo(params.botAgent),
    }),
    token: params.token,
    timeoutMs: 10_000,
    label: "sendTyping",
  });
}

/**
 * Notify server that client is stopping.
 */
export async function notifyStop(params: {
  baseUrl: string;
  token: string;
  botAgent?: string;
}): Promise<void> {
  try {
    await apiPostFetch({
      baseUrl: params.baseUrl,
      endpoint: "ilink/bot/msg/notifystop",
      body: JSON.stringify({ base_info: buildBaseInfo(params.botAgent) }),
      token: params.token,
      timeoutMs: 5_000,
      label: "notifyStop",
    });
  } catch (e) {
    logger.debug("notifyStop failed (safe to ignore):", e);
  }
}
