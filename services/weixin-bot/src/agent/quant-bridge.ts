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
      page_context: [
        "【终端环境】移动微信客户端（屏幕较窄，纯文本渲染）。",
        "【排版规范】",
        "1. 严禁输出任何 HTML 标签（如 <font>、<span>、<b> 等），微信客户端无法解析 HTML，会导致直接显示源码！",
        "2. 中国A股市场颜色与符号规范：上涨/浮盈必须为红色 🔺 或 +，下跌/浮亏必须为绿色 🔻 或 -，严禁使用海外绿涨红跌！",
        "3. 排版紧凑清晰：优先使用精炼要点，持仓数据请输出紧凑的结构化对比卡片，避免生成臃肿的多列超宽长表格。",
        "4. 结论先行，分段落重点突出，让用户在手机上无需反复滑动即可一目了然。",
      ].join("\n"),
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
  /**
   * 优化 1 & 优化 2: 将 Markdown 转化为移动微信端专属的高质感金融排版
   */
  public formatForWeixin(content: string): string {
    // 1. 彻底清洗所有 HTML 标签 (解决微信不支持 <font color="..."> 且出现源码与红绿反转的痛点)
    let text = content.replace(/<[^>]+>/g, "");

    // 2. 将 Markdown 表格自动转换为移动微信端易读的结构化键值与资产卡片
    text = this.convertMarkdownTablesToCards(text);

    // 3. 若存在旧版展开式 9 行持仓列表，智能压缩合并为精炼金融卡片 (必须在重命名标题前执行)
    const cardBlockRegex = /🔹\s*【([^】]+)】\s*\n((?:\s*▫️\s*[^\n]+\n?)+)/g;
    text = text.replace(cardBlockRegex, (match, headerCode, itemsText) => {
      const lines = itemsText.trim().split("\n");
      const dict: Record<string, string> = {};
      for (const l of lines) {
        const m = l.match(/▫️\s*([^:：]+)[:：]\s*(.+)/);
        if (m) {
          dict[m[1].trim()] = m[2].trim();
        }
      }

      const name = dict["标的名称"] || dict["名称"] || "";
      const code = headerCode.trim();
      const title = name ? `🔹 【${name} (${code})】` : `🔹 【${code}】`;

      const price = dict["最新价"] || dict["现价"] || "";
      const change = dict["当日涨跌"] || dict["涨跌幅"] || "";
      const cost = dict["成本价"] || dict["持仓成本"] || "";
      const quantity = dict["持仓数量"] || dict["持仓"] || dict["数量"] || "";
      const marketVal = dict["当前市值"] || dict["市值"] || "";
      const pnl = dict["浮动盈亏"] || dict["盈亏"] || "";
      const ret = dict["收益率"] || dict["盈亏率"] || "";

      const out: string[] = [title];
      if (price || cost) {
        const pStr = price ? (change ? `现价: ${price} (${change})` : `现价: ${price}`) : "";
        const cStr = cost ? `成本: ${cost}` : "";
        out.push(`   • ${[pStr, cStr].filter(Boolean).join(" ｜ ")}`);
      }
      if (marketVal || quantity) {
        const mStr = marketVal ? `市值: ${marketVal}` : "";
        const qStr = quantity ? `持仓: ${quantity}` : "";
        out.push(`   • ${[mStr, qStr].filter(Boolean).join(" ｜ ")}`);
      }
      if (pnl || ret) {
        const pnlStr = pnl ? (ret ? `浮动盈亏: ${pnl} (${ret})` : `浮动盈亏: ${pnl}`) : (ret ? `收益率: ${ret}` : "");
        out.push(`   • ${pnlStr}`);
      }

      const knownKeys = new Set([
        "标的名称", "名称", "持仓数量", "持仓", "数量", "成本价", "持仓成本",
        "最新价", "现价", "当日涨跌", "涨跌幅", "当前市值", "市值", "浮动盈亏", "盈亏", "收益率", "盈亏率"
      ]);
      for (const [k, v] of Object.entries(dict)) {
        if (!knownKeys.has(k)) {
          out.push(`   • ${k}: ${v}`);
        }
      }

      return out.join("\n") + "\n";
    });

    // 4. 分割线美化：将 --- 或 *** 替换为优雅雅致的虚线
    text = text.replace(/^\s*[-*_]{3,}\s*$/gm, "\n────────────────────────");

    // 5. 章节大标题美化：严格限制数字长度 1-2 位或汉字 1-3 位，杜绝匹配股票代码
    text = text.replace(/^[#\s]*[📌🔖🔸📈🔹💼📊💡⚠️🎯]*\s*【\s*([一二三四五六七八九十]{1,3}|\d{1,2})[、\.\s]*\s*([^】]+)】/gmu, (m, num, title) => {
      const t = title.trim();
      let icon = "📌";
      // 优先级严格按具体特征判断，避免“资产分析”误判为“资产总览”
      if (/分析|结构|诊断|归因|全景|画像/i.test(t)) icon = "📈";
      else if (/明细|持仓|清单|列表|标的/i.test(t)) icon = "📊";
      else if (/总览|概览|汇总|统计|账户/i.test(t)) icon = "💼";
      else if (/建议|操作|策略|结论/i.test(t)) icon = "💡";
      else if (/风险|提示|预警|注意/i.test(t)) icon = "⚠️";
      else if (/回测|表现|收益|净值/i.test(t)) icon = "🎯";
      return `${icon} 【${num}、${t}】`;
    });

    // 普通 Markdown 标题转化
    text = text.replace(/^####\s*(.+)$/gm, "🔸 $1");
    text = text.replace(/^###\s*(.+)$/gm, "📌 【$1】");
    text = text.replace(/^##\s*(.+)$/gm, "🔖 【$1】");
    text = text.replace(/^#\s*(.+)$/gm, "📈 【$1】");

    // 6. 引用块转化
    text = text.replace(/^>\s*(.+)$/gm, "💡 $1");

    // 7. 层次符号优化
    // 7.1 将一级数字编号标为高亮小标 (如 1. 配置均衡性 -> 🔸 1. 配置均衡性)
    text = text.replace(/^(\d+)\.\s+/gm, "🔸 $1. ");
    // 7.2 二级缩进列表美化 (保留层次缩进，移动端不散乱)
    text = text.replace(/^(\s{2,})[-*]\s+/gm, "   ▫️ ");
    // 7.3 一级无序列表统一
    text = text.replace(/^[-*]\s+/gm, "• ");

    // 8. 金融涨跌红绿符号规范 (A股市场标准：上涨/浮盈为红色🔺+，下跌/浮亏为绿色🔻-)
    // 8.1 预先剥离百分比前可能存在的冗余 emoji 避免重复嵌套
    text = text.replace(/[🔺🔴🟢🔻]\s*([+\-]\d+(?:\.\d+)?%)/gu, "$1");
    // 8.2 统一赋予标准红绿 emoji
    text = text.replace(/(?<!\d)\+(\d+(?:\.\d+)?%)/g, "🔺 +$1");
    text = text.replace(/(?<!\d)-(\d+(?:\.\d+)?%)/g, "🔻 -$1");
    // 8.3 修复括号内紧挨着的异常空格如 ( 🔺 +1.10%) -> (🔺 +1.10%)
    text = text.replace(/\(\s+([🔺🔻])/g, "($1");

    // 9. 移除 markdown 加粗 **
    text = text.replace(/\*\*([^*]+)\*\*/g, "$1");

    // 10. 压缩多余连续空行
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
          .map((c) => c.trim().replace(/<[^>]+>/g, ""))
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
          // 多列表格：检测是否为标的/持仓类表格
          const colMap: Record<string, number> = {};
          headers.forEach((h, idx) => {
            colMap[h.trim()] = idx;
          });

          // 查找各字段对应的索引
          const findIndex = (patterns: RegExp[]): number => {
            for (const [colName, idx] of Object.entries(colMap)) {
              if (patterns.some((p) => p.test(colName))) return idx;
            }
            return -1;
          };

          const idxCode = findIndex([/代码|symbol|code/i]);
          const idxName = findIndex([/名称|标的|股票|name/i]);
          const idxPrice = findIndex([/最新价|现价|收盘价|price/i]);
          const idxChange = findIndex([/当日涨跌|涨跌幅|涨跌|change/i]);
          const idxCost = findIndex([/成本价|持仓成本|成本|cost/i]);
          const idxQty = findIndex([/持仓数量|持仓|数量|份额|shares|volume/i]);
          const idxMarketVal = findIndex([/当前市值|市值|资产|market_value/i]);
          const idxPnl = findIndex([/浮动盈亏|盈亏金额|累计盈亏|pnl|profit/i]);
          const idxRet = findIndex([/收益率|盈亏比例|浮盈率|return/i]);

          // 判断是否命中持仓/金融类资产表格
          const isPositionTable = idxCode >= 0 || (idxName >= 0 && (idxPrice >= 0 || idxMarketVal >= 0));

          if (isPositionTable) {
            for (let i = 0; i < rowsBody.length; i++) {
              const row = rowsBody[i];
              const code = idxCode >= 0 ? row[idxCode] : "";
              const name = idxName >= 0 ? row[idxName] : "";

              let title = "";
              if (name && code && name !== code) {
                title = `🔹 【${name} (${code})】`;
              } else {
                title = `🔹 【${name || code || `标的 ${i + 1}`}】`;
              }
              result.push(title);

              // 现价 & 涨跌 & 成本
              const price = idxPrice >= 0 ? row[idxPrice] : "";
              const change = idxChange >= 0 ? row[idxChange] : "";
              const cost = idxCost >= 0 ? row[idxCost] : "";
              if (price || cost) {
                const pStr = price ? (change ? `现价: ${price} (${change})` : `现价: ${price}`) : "";
                const cStr = cost ? `成本: ${cost}` : "";
                result.push(`   • ${[pStr, cStr].filter(Boolean).join(" ｜ ")}`);
              }

              // 市值 & 持仓
              const marketVal = idxMarketVal >= 0 ? row[idxMarketVal] : "";
              const qty = idxQty >= 0 ? row[idxQty] : "";
              if (marketVal || qty) {
                const mStr = marketVal ? `市值: ${marketVal}` : "";
                const qStr = qty ? `持仓: ${qty}` : "";
                result.push(`   • ${[mStr, qStr].filter(Boolean).join(" ｜ ")}`);
              }

              // 浮动盈亏 & 收益率
              const pnl = idxPnl >= 0 ? row[idxPnl] : "";
              const ret = idxRet >= 0 ? row[idxRet] : "";
              if (pnl || ret) {
                const pnlStr = pnl ? (ret ? `浮动盈亏: ${pnl} (${ret})` : `浮动盈亏: ${pnl}`) : (ret ? `收益率: ${ret}` : "");
                result.push(`   • ${pnlStr}`);
              }

              // 处理其他未映射的列
              const mappedIndices = new Set([idxCode, idxName, idxPrice, idxChange, idxCost, idxQty, idxMarketVal, idxPnl, idxRet]);
              for (let j = 0; j < headers.length; j++) {
                if (!mappedIndices.has(j) && row[j]) {
                  result.push(`   • ${headers[j]}: ${row[j]}`);
                }
              }

              if (i < rowsBody.length - 1) {
                result.push("");
              }
            }
          } else {
            // 普通非持仓多列表格
            for (let i = 0; i < rowsBody.length; i++) {
              const row = rowsBody[i];
              const primaryName = row[0] || `项 ${i + 1}`;
              result.push(`🔹 【${primaryName}】`);
              for (let j = 1; j < headers.length; j++) {
                const h = headers[j] || `指标${j}`;
                const val = row[j] || "--";
                result.push(`   • ${h}: ${val}`);
              }
              if (i < rowsBody.length - 1) {
                result.push("");
              }
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
