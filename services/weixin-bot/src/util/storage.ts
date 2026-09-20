import fs from "node:fs";
import path from "node:path";

export interface BotSession {
  token: string;
  accountId: string;
  baseUrl: string;
  userId?: string;
  getUpdatesBuf?: string;
  savedAt: number;
}

export class SessionStorage {
  private filePath: string;

  constructor(storageDir: string = "./.data") {
    if (!fs.existsSync(storageDir)) {
      fs.mkdirSync(storageDir, { recursive: true });
    }
    this.filePath = path.join(storageDir, "session.json");
  }

  load(): BotSession | null {
    try {
      if (!fs.existsSync(this.filePath)) {
        return null;
      }
      const data = fs.readFileSync(this.filePath, "utf-8");
      return JSON.parse(data) as BotSession;
    } catch {
      return null;
    }
  }

  save(session: Partial<BotSession> & { token: string; accountId: string }): void {
    const existing = this.load();
    const updated: BotSession = {
      ...(existing ?? {}),
      ...session,
      savedAt: Date.now(),
      baseUrl: session.baseUrl || existing?.baseUrl || "https://ilinkai.weixin.qq.com",
    };
    fs.writeFileSync(this.filePath, JSON.stringify(updated, null, 2), "utf-8");
  }

  saveUpdatesBuf(buf: string): void {
    const session = this.load();
    if (session) {
      session.getUpdatesBuf = buf;
      fs.writeFileSync(this.filePath, JSON.stringify(session, null, 2), "utf-8");
    }
  }

  clear(): void {
    try {
      if (fs.existsSync(this.filePath)) {
        fs.unlinkSync(this.filePath);
      }
    } catch {
      // Ignore deletion errors
    }
  }
}
