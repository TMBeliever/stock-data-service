import type { BotMessage } from "../client/bot.js";
import { logger } from "../util/logger.js";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface UserSessionContext {
  sessionId: string;
  history: ChatMessage[];
  lastActive: number;
}

export interface QuantBridgeOptions {
  quantAgentUrl?: string;
  defaultModel?: string;
  maxHistoryTurns?: number;
  getUserToken?: () => string | null;
  getBoundUserId?: () => string | null;
}

export class QuantAgentBridge {
  private quantAgentUrl: string;
  private defaultModel: string;
  private maxHistoryTurns: number;
  private getUserToken?: () => string | null;
  private getBoundUserId?: () => string | null;

  // 用户会话上下文存储: Map<sender_id, UserSessionContext>
  private userSessions = new Map<string, UserSessionContext>();

  constructor(options: QuantBridgeOptions = {}) {
    this.quantAgentUrl = (options.quantAgentUrl || process.env.QUANT_AGENT_URL || "http://127.0.0.1:8060").replace(/\/+$/, "");
    this.defaultModel = options.defaultModel || process.env.DEFAULT_MODEL || "agt-gemini-3.8-flash";
    this.maxHistoryTurns = options.maxHistoryTurns || 8;
    this.getUserToken = options.getUserToken;
    this.getBoundUserId = options.getBoundUserId;
  }

  /**
   * 获取或初始化用户的会话上下文
   */
  public getOrCreateSession(userId: string): UserSessionContext {
    let ctx = this.userSessions.get(userId);
    // 超过 1 小时无交互，自动刷新会话 ID
    const oneHour = 60 * 60 * 1000;
    if (!ctx || Date.now() - ctx.lastActive > oneHour) {
      ctx = {
        sessionId: `wx_sess_${userId.replace(/[^a-zA-Z0-9_-]/g, "")}_${Date.now()}`,
        history: [],
        lastActive: Date.now(),
      };
      this.userSessions.set(userId, ctx);
    }
    return ctx;
  }

  /**
   * 显式重置并开启新会话 (处理 /new 等指令)
   * 既清空微信端滑动窗口历史，又显式通知后端智能体与底层 ai-core 释放旧会话 Worker
   */
  public resetSession(userId: string): string {
    const oldSession = this.userSessions.get(userId);
    const oldSessionId = oldSession?.sessionId;

    const newSessionId = `wx_sess_${userId.replace(/[^a-zA-Z0-9_-]/g, "")}_${Date.now()}`;
    this.userSessions.set(userId, {
      sessionId: newSessionId,
      history: [],
      lastActive: Date.now(),
    });

    // 异步通知 quant-agent 及底层 ai-core 显式销毁旧会话 Worker 进程
    if (oldSessionId) {
      fetch(`${this.quantAgentUrl}/api/v1/agent/sessions/${oldSessionId}`, {
        method: "DELETE",
      }).catch((e) => {
        logger.debug("[QuantBridge] 异步通知重置旧会话忽略:", e);
      });
    }

    logger.info(`[QuantBridge] 用户 ${userId} 会话已重置: 旧会话=${oldSessionId || "无"} -> 新会话=${newSessionId}`);
    return newSessionId;
  }

  /**
   * 处理微信收到的用户消息
   */
  public async handleMessage(msg: BotMessage): Promise<void> {
    const rawText = msg.text?.trim() || "";
    if (!rawText) return;

    const sender = msg.sender;
    const lowerText = rawText.toLowerCase();

    // 1. 处理系统级命令：/new, /clear, /reset, 新会话
    if (["/new", "/clear", "/reset", "新会话", "开启新会话"].includes(lowerText)) {
      this.resetSession(sender);
      await msg.reply("✨ 已为您开启全新会话！上一轮上下文已归档。\n请随时向我提问量化投研、自选行情或策略分析问题。");
      return;
    }

    // 2. 处理帮助命令：/help
    if (["/help", "帮助", "功能"].includes(lowerText)) {
      const helpText = [
        "📊 【微信量化智能助理使用指南】",
        "",
        "💡 您可以直接用自然语言向我提问：",
        "• 行情估值：\"比亚迪现在的估值如何？\"",
        "• 个人自选：\"查一下我的自选股今天表现\"",
        "• 策略回测：\"帮我测试一下510300的双均线策略\"",
        "• 财报分析：\"宁德时代最近的营收和利润增速怎样？\"",
        "",
        "⚙️ 常用指令：",
        "• /new 或 新会话：清空记忆，开启全新对话",
        "• /help：查看本帮助菜单",
      ].join("\n");
      await msg.reply(helpText);
      return;
    }

    // 3. 正常业务消息：调用 quant-agent 处理
    await this.processChatWithAgent(msg, rawText);
  }

  /**
   * 向 quant-agent 发送流式对话请求并汇聚回答
   */
  private async processChatWithAgent(msg: BotMessage, userQuery: string): Promise<void> {
    const sender = msg.sender;
    const session = this.getOrCreateSession(sender);
    session.lastActive = Date.now();

    // 追加用户消息至历史
    session.history.push({ role: "user", content: userQuery });

    // 滑动窗口控制：最多保留最近 maxHistoryTurns 轮 (2 * turns 条)
    const maxMessages = this.maxHistoryTurns * 2;
    if (session.history.length > maxMessages) {
      session.history = session.history.slice(session.history.length - maxMessages);
    }

    // 状态提示：微信正在输入
    await msg.typing(1);

    const token = this.getUserToken?.() || "";
    const boundUserId = this.getBoundUserId?.() || sender;

    const endpoint = `${this.quantAgentUrl}/api/v1/agent/chat`;

    const requestBody = {
      messages: session.history,
      model: this.defaultModel,
      agent_mode: "quant",
      user_id: boundUserId,
      session_id: session.sessionId,
      page_context: "【调用来源】移动微信客户端。排版请遵循结论先行、结构清晰原则，多用要点列表和短句，避免输出超宽长表格。",
      thinking_level: "medium",
    };

    logger.info(`[QuantBridge] 转发微信消息 -> quant-agent: sender=${sender}, user_id=${boundUserId}, session_id=${session.sessionId}`);

    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = token.startsWith("Bearer ") ? token : `Bearer ${token}`;
      }

      const response = await fetch(endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`量化智能体响应异常 (HTTP ${response.status}): ${errorText}`);
      }

      if (!response.body) {
        throw new Error("量化智能体未返回有效数据流");
      }

      // 读取 SSE 事件流
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let accumulatedText = "";
      let lastReportedTool = "";
      let hasSentProgress = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            currentEvent = "";
            continue;
          }

          if (trimmed.startsWith("event:")) {
            currentEvent = trimmed.slice(6).trim();
            continue;
          }

          if (trimmed.startsWith("data:")) {
            const dataStr = trimmed.slice(5).trim();
            try {
              const data = JSON.parse(dataStr);
              if (currentEvent === "tool_call") {
                const toolName = data.name || "量化工具";
                if (toolName !== lastReportedTool) {
                  lastReportedTool = toolName;
                  logger.info(`[QuantBridge] Agent 执行工具: ${toolName}`);
                  // 保持 typing 状态
                  await msg.typing(1);

                  // 优化 3: 触发耗时工具调用时，前置发送轻量进度气泡，消除黑盒等待焦虑
                  if (!hasSentProgress) {
                    hasSentProgress = true;
                    const desc = this.getToolDescription(toolName);
                    msg.reply(`🔍 正在调取【${desc}】深度分析中，请稍候...`).catch((e) => {
                      logger.debug("[QuantBridge] 发送进度气泡异常忽略:", e);
                    });
                  }
                }
              } else if (currentEvent === "message") {
                if (data.delta) {
                  accumulatedText += data.delta;
                }
              }
            } catch {
              // 忽略单行非 JSON 数据
            }
          }
        }
      }

      const replyContent = accumulatedText.trim();
      if (!replyContent) {
        await msg.reply("抱歉，我未能生成分析结果，请稍后重试或尝试重新描述问题。");
        return;
      }

      // 记录 assistant 回复至多轮历史
      session.history.push({ role: "assistant", content: replyContent });

      // 针对微信端进行排版重构与美化 (优化 1: 表格卡片化, 优化 2: 涨跌符号与视觉锚点增强)
      const formattedReply = this.formatForWeixin(replyContent);

      await msg.reply(formattedReply);
      logger.info(`[QuantBridge] 回复已成功发送至微信: sender=${sender}`);
    } catch (err: any) {
      logger.error("[QuantBridge] 处理微信量化对话失败:", err);
      await msg.reply(`⚠️ 量化服务响应出错：${err.message || "内部错误，请稍后再试"}`);
    } finally {
      await msg.typing(2);
    }
  }

  /**
   * 工具名映射为自然语言解释
   */
  private getToolDescription(toolName: string): string {
    const map: Record<string, string> = {
      get_stock_quote: "实时盘口快照与量价行情",
      get_stock_spot: "实时行情盘口",
      get_kline_data: "历史量化K线与技术均线",
      get_financial_metrics: "最新财报指标与分红估值",
      run_strategy_backtest: "历史多因子策略回测",
      get_user_watchlist: "个人自选股监控池",
      get_user_strategies: "个人实盘策略库",
      python_interpreter: "量化多因子分析与指标运算",
      search_news: "财经资讯与舆情动态",
    };
    return map[toolName] || "量化底层数据与多因子指标";
  }

  /**
   * 优化 1 & 优化 2: 将 Markdown 转化为移动微信端友好、高可读性的排版
   */
  public formatForWeixin(content: string): string {
    // 1. 优化 1: 将 Markdown 表格自动转换为移动微信端易读的结构化键值卡片
    let text = this.convertMarkdownTablesToCards(content);

    // 2. 优化 2: 金融视觉符号与排版规范增强
    // 2.1 标题层级转化 (先长后短避免部分替换)
    text = text.replace(/^####\s*(.+)$/gm, "🔸 【$1】");
    text = text.replace(/^###\s*(.+)$/gm, "📌 【$1】");
    text = text.replace(/^##\s*(.+)$/gm, "🔖 【$1】");
    text = text.replace(/^#\s*(.+)$/gm, "📈 【$1】");

    // 2.2 引用块转化
    text = text.replace(/^>\s*(.+)$/gm, "💡 $1");

    // 2.3 无序列表统一为易读实心圆点
    text = text.replace(/^[\*\-]\s+/gm, "• ");

    // 2.4 金融涨跌红绿符号增强 (仅在未包含 emoji 时自动添加)
    text = text.replace(/(?<![🔺🔴🟢🔻\d])\+(\d+(?:\.\d+)?%)/g, "🔺 +$1");
    text = text.replace(/(?<![🔺🔴🟢🔻\d])\-(\d+(?:\.\d+)?%)/g, "🔻 -$1");

    // 2.5 移除冗余 ** 加粗符号，微信不支持加粗且影响观感
    text = text.replace(/\*\*([^*]+)\*\*/g, "$1");

    // 2.6 压缩过多连续空行 (最多保留 1 个空行)
    text = text.replace(/\n{3,}/g, "\n\n");

    return text.trim();
  }

  /**
   * 将 Markdown 表格自动转换为移动微信端易读的结构化键值卡片
   */
  private convertMarkdownTablesToCards(content: string): string {
    const lines = content.split("\n");
    const result: string[] = [];
    let inTable = false;
    let tableLines: string[] = [];

    const flushTable = () => {
      if (tableLines.length === 0) return;
      const rows = tableLines.map((l) =>
        l
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((c) => c.trim())
      );

      // 过滤掉表格分割线如 |---|---|
      const dataRows = rows.filter((r) => !r.every((c) => /^[-:\s]+$/.test(c)));
      if (dataRows.length >= 2) {
        const headers = dataRows[0];
        const rowsBody = dataRows.slice(1);

        if (headers.length === 2) {
          // 双列键值对表格 (如 指标 | 数值)
          for (const row of rowsBody) {
            const k = row[0] || "";
            const v = row[1] || "";
            if (k && v) {
              result.push(`• ${k}: ${v}`);
            } else if (k) {
              result.push(`• ${k}`);
            }
          }
        } else {
          // 多列矩阵表格 (如 股票 | 最新价 | 涨跌幅 | PE)
          for (let i = 0; i < rowsBody.length; i++) {
            const row = rowsBody[i];
            const primaryName = row[0] || `项 ${i + 1}`;
            result.push(`🔹 【${primaryName}】`);
            for (let j = 1; j < headers.length; j++) {
              const h = headers[j] || `指标${j}`;
              const val = row[j] || "--";
              result.push(`   ▫️ ${h}: ${val}`);
            }
            if (i < rowsBody.length - 1) {
              result.push("");
            }
          }
        }
      } else {
        result.push(...tableLines);
      }
      tableLines = [];
      inTable = false;
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();
      const isTableRow = trimmed.startsWith("|") && trimmed.includes("|", 1);

      if (isTableRow) {
        inTable = true;
        tableLines.push(trimmed);
      } else {
        if (inTable) {
          flushTable();
        }
        result.push(line);
      }
    }
    if (inTable) {
      flushTable();
    }

    return result.join("\n");
  }
}
