FROM node:22-alpine AS builder

WORKDIR /app

# 安装 pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# 复制依赖配置
COPY package.json pnpm-lock.yaml* tsconfig.json ./
RUN pnpm install --frozen-lockfile || pnpm install

# 复制源码并编译 TypeScript
COPY src/ ./src/
RUN pnpm build

# 生产运行阶段
FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8095
ENV STORAGE_DIR=/app/.data

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --prod --frozen-lockfile || pnpm install --prod

COPY --from=builder /app/dist ./dist

# 创建持久化数据目录
RUN mkdir -p /app/.data

EXPOSE 8095

CMD ["node", "dist/main.js"]
