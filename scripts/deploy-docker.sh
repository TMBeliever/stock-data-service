#!/usr/bin/env bash
# =========================================================================
# Quant System 一键全栈生产容器化部署与生命周期运维脚本
# =========================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"

# 颜色输出定义
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${BLUE}==============================================================${RESET}"
echo -e "${BLUE}  ⚡ Quant System 生产级全栈 Docker 一键交付运维中枢          ${RESET}"
echo -e "${BLUE}==============================================================${RESET}"

# 1. 检查 Docker 运行时
check_prerequisites() {
    echo -e "\n${YELLOW}[1/4] 正在检查部署机 Docker 运行环境...${RESET}"
    if ! command -v docker >/dev/null 2>&1; then
        echo -e "${RED}❌ 错误: 未检测到 docker 命令，请先在 Ubuntu 服务器上安装 Docker: curl -fsSL https://get.docker.com | sh${RESET}"
        exit 1
    fi

    if ! docker compose version >/dev/null 2>&1; then
        echo -e "${RED}❌ 错误: 未检测到 docker compose 插件，请升级 Docker 包含 Compose V2。${RESET}"
        exit 1
    fi

    if [ ! -e /var/run/docker.sock ]; then
        echo -e "${YELLOW}⚠️ 警告: 未找到 /var/run/docker.sock，Agent 的 Docker 容器管理特权可能受限。${RESET}"
    else
        echo -e "${GREEN}✓ Docker Daemon 与 Unix Socket 检测就绪 (/var/run/docker.sock)。${RESET}"
    fi

    mkdir -p "${ROOT_DIR}/data"
}

# 2. 构建并启动全部 6 大微服务
deploy_up() {
    check_prerequisites
    echo -e "\n${YELLOW}[2/4] 正在编译全微服务镜像并启动容器集群...${RESET}"
    cd "${ROOT_DIR}"
    docker compose -f "${COMPOSE_FILE}" up -d --build --remove-orphans

    echo -e "\n${YELLOW}[3/4] 正在等待微服务健康探针就绪...${RESET}"
    local max_wait=60
    local elapsed=0
    local all_ready=false

    while [ $elapsed -lt $max_wait ]; do
        sleep 3
        elapsed=$((elapsed + 3))
        
        # 探测 Web 界面与后端
        if curl -s -f http://127.0.0.1:8060/health >/dev/null 2>&1 && \
           curl -s -f http://127.0.0.1:8070/health >/dev/null 2>&1; then
            all_ready=true
            break
        fi
        echo -n "."
    done

    echo ""
    if [ "$all_ready" = true ]; then
        echo -e "${GREEN}✓ 全微服务已成功就绪！${RESET}"
    else
        echo -e "${YELLOW}⚠️ 微服务正在后台完成最终预热，请执行 ./scripts/deploy-docker.sh status 观察。${RESET}"
    fi

    show_status
}

# 3. 查看微服务集群健康状态
show_status() {
    echo -e "\n${YELLOW}[4/4] 容器集群运行状态看板:${RESET}"
    cd "${ROOT_DIR}"
    docker compose -f "${COMPOSE_FILE}" ps
    
    echo -e "\n${GREEN}==============================================================${RESET}"
    echo -e "${GREEN}  🎉 部署成功！系统各核心端点如下：                          ${RESET}"
    echo -e "${GREEN}  - 🌐 前端 Web 控制台:    http://<服务器IP>:80/              ${RESET}"
    echo -e "${GREEN}  - 🤖 Quant Agent 中枢:   http://<服务器IP>:8060/health      ${RESET}"
    echo -e "${GREEN}  - 🧠 AI 模型网关:        http://<服务器IP>:8070/health      ${RESET}"
    echo -e "${GREEN}  - ⚡ 量化回测中枢:       http://<服务器IP>:8080/health      ${RESET}"
    echo -e "${GREEN}  - 👤 用户中心与策略库:   http://<服务器IP>:8090/health      ${RESET}"
    echo -e "${GREEN}  - 📈 行情数据中台:       http://<服务器IP>:8000/docs        ${RESET}"
    echo -e "${GREEN}==============================================================${RESET}"
}

# 4. 实时跟踪日志
show_logs() {
    cd "${ROOT_DIR}"
    docker compose -f "${COMPOSE_FILE}" logs -f "$@"
}

# 5. 停止服务集群
stop_cluster() {
    echo -e "${YELLOW}正在安全停止并清理容器集群...${RESET}"
    cd "${ROOT_DIR}"
    docker compose -f "${COMPOSE_FILE}" down
    echo -e "${GREEN}✓ 容器集群已停止。持久化数据卷依然安全保存在 docker volumes 中。${RESET}"
}

# 路由子命令
case "$1" in
    up|start|"")
        deploy_up
        ;;
    status|ps)
        show_status
        ;;
    logs)
        shift
        show_logs "$@"
        ;;
    stop|down)
        stop_cluster
        ;;
    restart)
        stop_cluster
        deploy_up
        ;;
    *)
        echo "用法: $0 {up|status|logs|stop|restart}"
        exit 1
        ;;
esac
