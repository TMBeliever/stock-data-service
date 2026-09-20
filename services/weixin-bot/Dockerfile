FROM node:22-alpine AS builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json tsconfig.json ./
RUN pnpm install

COPY src/ ./src/
RUN pnpm build

# 生产运行阶段
FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8095
ENV STORAGE_DIR=/app/.data

COPY package.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

# 创建持久化数据目录
RUN mkdir -p /app/.data

EXPOSE 8095

CMD ["node", "dist/main.js"]
