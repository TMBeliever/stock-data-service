export enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
}

class Logger {
  public level: LogLevel = LogLevel.INFO;

  private formatMessage(level: string, msg: string): string {
    const now = new Date().toLocaleTimeString();
    return `[${now}] [${level}] ${msg}`;
  }

  debug(msg: string, ...args: unknown[]) {
    if (this.level <= LogLevel.DEBUG) {
      console.debug(this.formatMessage("DEBUG", msg), ...args);
    }
  }

  info(msg: string, ...args: unknown[]) {
    if (this.level <= LogLevel.INFO) {
      console.log(this.formatMessage("INFO", msg), ...args);
    }
  }

  warn(msg: string, ...args: unknown[]) {
    if (this.level <= LogLevel.WARN) {
      console.warn(this.formatMessage("WARN", msg), ...args);
    }
  }

  error(msg: string, ...args: unknown[]) {
    if (this.level <= LogLevel.ERROR) {
      console.error(this.formatMessage("ERROR", msg), ...args);
    }
  }
}

export const logger = new Logger();
