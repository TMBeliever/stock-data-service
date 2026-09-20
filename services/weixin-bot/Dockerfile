FROM node:22-alpine AS builder

WORKDIR /app

# 配置国内镜像源加速构建，避免网络超时
RUN npm config set registry https://registry.npmmirror.com

COPY package.json tsconfig.json ./
RUN npm install

COPY src/ ./src/
RUN npm run build

# 生产运行阶段
FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8095
ENV STORAGE_DIR=/app/.data

# 配置国内镜像源
RUN npm config set registry https://registry.npmmirror.com

COPY package.json ./
# 仅安装生产依赖 (qrcode, qrcode-terminal, zod)，为标准实体目录，杜绝软链接丢失异常
RUN npm install --omit=dev

# 拷贝编译好的 JavaScript 产物
COPY --from=builder /app/dist ./dist

# 创建持久化数据目录
RUN mkdir -p /app/.data

EXPOSE 8095

CMD ["node", "dist/main.js"]
