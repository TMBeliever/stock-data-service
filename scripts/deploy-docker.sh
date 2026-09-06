#!/usr/bin/env bash
# =========================================================================
# Quant System 一键全栈生产容器化部署与增量生命周期运维脚本
# 支持精准增量部署：代码修改的服务才重新构建并更新，未修改的跳过
# =========================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
CACHE_DIR="${ROOT_DIR}/.deploy_cache"

# 全部微服务定义（按依赖分层顺序：数据底座 -> 计算中枢 -> 业务/Agent -> 前端网关）
ALL_SERVICES=(
    "stock-data"
    "ai-core"
    "quant-server"
    "common-server"
    "quant-agent"
    "web-admin"
)

# 终端色彩定义
GREEN="\033[32m"
YELLOW="\033[33m"
BLUE="\033[34m"
RED="\033[31m"
CYAN="\033[36m"
GRAY="\033[90m"
BOLD="\033[1m"
RESET="\033[0m"

# 1. 打印横幅
print_banner() {
    echo -e "${BLUE}==============================================================${RESET}"
    echo -e "${BLUE}  ⚡ Quant System 生产级微服务增量交付与运维中枢          ${RESET}"
    echo -e "${BLUE}==============================================================${RESET}"
}

# 2. 检查 Docker 运行时环境
check_prerequisites() {
    echo -e "\n${YELLOW}[1/4] 正在检查 Docker 运行环境...${RESET}"
    if ! command -v docker >/dev/null 2>&1; then
        echo -e "${RED}❌ 错误: 未检测到 docker 命令，请先安装 Docker。${RESET}"
        exit 1
    fi

    if ! docker compose version >/dev/null 2>&1; then
        echo -e "${RED}❌ 错误: 未检测到 docker compose 插件，请升级 Docker 包含 Compose V2。${RESET}"
        exit 1
    fi

    if [ ! -e /var/run/docker.sock ]; then
        echo -e "${YELLOW}⚠️ 警告: 未找到 /var/run/docker.sock，Docker 管理特权可能受限。${RESET}"
    else
        echo -e "${GREEN}✓ Docker Daemon 与 Unix Socket 检测就绪 (/var/run/docker.sock)。${RESET}"
    fi

    mkdir -p "${ROOT_DIR}/data"
    mkdir -p "${CACHE_DIR}"
}

# 3. 各微服务的源码与依赖监听路径定义
get_service_watch_paths() {
    local svc="$1"
    case "$svc" in
        web-admin)
            echo "apps/web-admin"
            ;;
        quant-agent)
            echo "services/quant-agent packages/agent-core packages/ai-core packages/quant-core packages/stock-data pyproject.toml"
            ;;
        ai-core)
            echo "packages/ai-core"
            ;;
        quant-server)
            echo "services/quant-server packages/quant-core pyproject.toml"
            ;;
        common-server)
            echo "services/common-server"
            ;;
        stock-data)
            echo "packages/stock-data"
            ;;
        *)
            echo ""
            ;;
    esac
}

# 4. 各微服务的健康检查端点定义
get_service_health_endpoint() {
    local svc="$1"
    case "$svc" in
        web-admin)
            echo "http://127.0.0.1:${WEB_PORT:-80}/"
            ;;
        quant-agent)
            echo "http://127.0.0.1:8060/health"
            ;;
        ai-core)
            echo "http://127.0.0.1:8070/health"
            ;;
        quant-server)
            echo "http://127.0.0.1:8080/api/v1/health"
            ;;
        common-server)
            echo "http://127.0.0.1:8090/health"
            ;;
        stock-data)
            echo "http://127.0.0.1:8000/api/v1/system/storage"
            ;;
        *)
            echo ""
            ;;
    esac
}

# 5. 计算服务的代码与配置 SHA256 综合指纹
compute_service_hash() {
    local svc="$1"
    local paths
    paths=$(get_service_watch_paths "$svc")
    if [ -z "$paths" ]; then
        echo "unknown"
        return
    fi

    # 将 docker-compose.prod.yml 纳入公共监听，编排文件改动时促成相关更新
    cd "${ROOT_DIR}"
    local all_targets=($paths "docker-compose.prod.yml")

    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        (
            git ls-files -s -- "${all_targets[@]}" 2>/dev/null
            git diff HEAD -- "${all_targets[@]}" 2>/dev/null
            git ls-files --others --exclude-standard -- "${all_targets[@]}" 2>/dev/null | while read -r f; do
                if [ -f "$f" ]; then
                    if command -v sha256sum >/dev/null 2>&1; then
                        sha256sum "$f"
                    elif command -v shasum >/dev/null 2>&1; then
                        shasum -a 256 "$f" 2>/dev/null
                    else
                        md5 -q "$f" 2>/dev/null
                    fi
                fi
            done
        ) | (command -v sha256sum >/dev/null 2>&1 && sha256sum || (command -v shasum >/dev/null 2>&1 && shasum -a 256) || md5) | awk '{print $1}'
    else
        # 兼容无 git 时的纯文件哈希计算
        find "${all_targets[@]}" -type f \
            ! -path '*/.*' \
            ! -path '*/node_modules/*' \
            ! -path '*/dist/*' \
            ! -path '*/__pycache__/*' \
            ! -path '*/.pytest_cache/*' \
            ! -path '*/data/*' \
            -exec ls -l --full-time {} + 2>/dev/null | (command -v sha256sum >/dev/null 2>&1 && sha256sum || md5) | awk '{print $1}'
    fi
}

# 6. 判断微服务容器当前是否在运行
is_service_running() {
    local svc="$1"
    cd "${ROOT_DIR}"
    local cid
    cid=$(docker compose -f "${COMPOSE_FILE}" ps -q "$svc" 2>/dev/null || true)
    if [ -z "$cid" ]; then
        return 1
    fi
    local status
    status=$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)
    if [ "$status" = "running" ]; then
        return 0
    else
        return 1
    fi
}

# 7. 变更检测与分析 (Dry-run / Check)
check_diff() {
    mkdir -p "${CACHE_DIR}"
    echo -e "\n${CYAN}🔍 正在比对各微服务源码与容器状态...${RESET}"
    printf "%-16s %-12s %-20s %s\n" "微服务名称" "容器状态" "代码指纹状态" "部署动作建议"
    echo "----------------------------------------------------------------------"

    for svc in "${ALL_SERVICES[@]}"; do
        local cur_hash
        cur_hash=$(compute_service_hash "$svc")
        local cached_hash=""
        if [ -f "${CACHE_DIR}/${svc}.hash" ]; then
            cached_hash=$(cat "${CACHE_DIR}/${svc}.hash" 2>/dev/null || true)
        fi

        local running=false
        if is_service_running "$svc"; then
            running=true
        fi

        local status_str="已停止"
        if [ "$running" = true ]; then
            status_str="${GREEN}运行中${RESET}"
        else
            status_str="${RED}未运行${RESET}"
        fi

        local code_status=""
        local action=""
        if [ -z "$cached_hash" ]; then
            code_status="${YELLOW}首次无记录${RESET}"
            action="${BOLD}${YELLOW}需初始构建${RESET}"
        elif [ "$cur_hash" != "$cached_hash" ]; then
            code_status="${RED}代码已修改${RESET}"
            action="${BOLD}${RED}需增量更新${RESET}"
        else
            code_status="${GREEN}无代码改动${RESET}"
            if [ "$running" = true ]; then
                action="${GRAY}跳过 (保持)${RESET}"
            else
                action="${YELLOW}需启动运行${RESET}"
            fi
        fi

        printf "%-16s %-20b %-26b %b\n" "$svc" "$status_str" "$code_status" "$action"
    done
    echo "----------------------------------------------------------------------"
}

# 8. 核心：增量构建与部署
deploy_incremental() {
    local force=false
    local custom_services=()

    # 解析附加参数
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --force|-f|force)
                force=true
                shift
                ;;
            *)
                # 如果传入了具体的服务名
                custom_services+=("$1")
                shift
                ;;
        esac
    done

    check_prerequisites

    echo -e "\n${YELLOW}[2/4] 正在分析微服务改动状态 (增量比对)...${RESET}"
    mkdir -p "${CACHE_DIR}"

    local services_to_build=()
    local services_to_skip=()
    local new_hashes=()

    local targets=("${ALL_SERVICES[@]}")
    if [ ${#custom_services[@]} -gt 0 ]; then
        targets=("${custom_services[@]}")
        echo -e "${CYAN}🎯 指定部署目标服务: ${targets[*]}${RESET}"
    fi

    for svc in "${targets[@]}"; do
        local cur_hash
        cur_hash=$(compute_service_hash "$svc")
        local cached_hash=""
        if [ -f "${CACHE_DIR}/${svc}.hash" ]; then
            cached_hash=$(cat "${CACHE_DIR}/${svc}.hash" 2>/dev/null || true)
        fi

        local is_running=false
        if is_service_running "$svc"; then
            is_running=true
        fi

        if [ "$force" = true ]; then
            echo -e "  ${BOLD}${YELLOW}[强制更新]${RESET} ${svc}: 收到强制全量构建参数"
            services_to_build+=("$svc")
        elif [ ${#custom_services[@]} -gt 0 ]; then
            echo -e "  ${BOLD}${YELLOW}[指定更新]${RESET} ${svc}: 明确指定部署"
            services_to_build+=("$svc")
        elif [ -z "$cached_hash" ]; then
            echo -e "  ${BOLD}${YELLOW}[首次部署]${RESET} ${svc}: 无历史部署记录"
            services_to_build+=("$svc")
        elif [ "$cur_hash" != "$cached_hash" ]; then
            echo -e "  ${BOLD}${RED}[代码改动]${RESET} ${svc}: 源码指纹已改变 (${cached_hash:0:8} -> ${cur_hash:0:8})"
            services_to_build+=("$svc")
        elif [ "$is_running" = false ]; then
            echo -e "  ${BOLD}${YELLOW}[异常拉起]${RESET} ${svc}: 代码无改动但容器未运行，执行启动"
            services_to_build+=("$svc")
        else
            echo -e "  ${GRAY}[无需改动] ${svc}: 代码无变化且容器正常运行中 (跳过构建)${RESET}"
            services_to_skip+=("$svc")
        fi
    done

    # 若所有服务均无需更新
    if [ ${#services_to_build[@]} -eq 0 ]; then
        echo -e "\n${GREEN}✨ 完美！所有微服务均已是最新版本且正常运行，无需重复构建部署。${RESET}"
        echo -e "${GRAY}💡 如需强制全量重新构建，请使用: ./scripts/deploy-docker.sh up --force${RESET}"
        show_status
        return 0
    fi

    echo -e "\n${YELLOW}⚡ 本次增量更新服务清单: ${BOLD}${GREEN}${services_to_build[*]}${RESET}"
    cd "${ROOT_DIR}"

    # 1. 仅对发生变化的服务执行 docker compose build
    echo -e "\n${YELLOW}[3/4] 仅对改动的服务执行增量镜像编译...${RESET}"
    docker compose -f "${COMPOSE_FILE}" build "${services_to_build[@]}"

    # 2. 重启/拉起变更的服务（--no-deps 确保不盲目重新拉起未修改的服务）
    echo -e "\n${YELLOW}正在启动更新后的微服务容器...${RESET}"
    docker compose -f "${COMPOSE_FILE}" up -d --no-deps "${services_to_build[@]}"

    # 3. 针对性健康探针等待（只探测本次更新的服务）
    echo -e "\n${YELLOW}正在针对更新的服务进行健康校验...${RESET}"
    local max_wait=40
    for svc in "${services_to_build[@]}"; do
        local url
        url=$(get_service_health_endpoint "$svc")
        if [ -n "$url" ]; then
            echo -n "  ⏳ 检查 $svc ($url) ... "
            local elapsed=0
            local ok=false
            while [ $elapsed -lt $max_wait ]; do
                if curl -s -f "$url" >/dev/null 2>&1; then
                    ok=true
                    break
                fi
                sleep 2
                elapsed=$((elapsed + 2))
            done
            if [ "$ok" = true ]; then
                echo -e "${GREEN}就绪 (${elapsed}s)${RESET}"
            else
                echo -e "${YELLOW}待就绪 (正在后台启动)${RESET}"
            fi
        fi

        # 更新并持久化当前代码哈希缓存
        local final_hash
        final_hash=$(compute_service_hash "$svc")
        echo "$final_hash" > "${CACHE_DIR}/${svc}.hash"
    done

    echo -e "\n${GREEN}✓ 增量部署与指纹记录已成功完成！${RESET}"
    show_status
}

# 9. 查看微服务集群运行看板
show_status() {
    echo -e "\n${YELLOW}[4/4] 容器集群运行状态看板:${RESET}"
    cd "${ROOT_DIR}"
    docker compose -f "${COMPOSE_FILE}" ps
    
    echo -e "\n${GREEN}==============================================================${RESET}"
    echo -e "${GREEN}  🎉 Quant System 生产环境各微服务访问入口：                   ${RESET}"
    echo -e "${GREEN}  - 🌐 前端 Web 控制台:    http://<服务器IP>:${WEB_PORT:-80}/         ${RESET}"
    echo -e "${GREEN}  - 🤖 Quant Agent 中枢:   http://<服务器IP>:8060/health      ${RESET}"
    echo -e "${GREEN}  - 🧠 AI 模型网关:        http://<服务器IP>:8070/health      ${RESET}"
    echo -e "${GREEN}  - ⚡ 量化回测中枢:       http://<服务器IP>:8080/health      ${RESET}"
    echo -e "${GREEN}  - 👤 用户中心与策略库:   http://<服务器IP>:8090/health      ${RESET}"
    echo -e "${GREEN}  - 📈 行情数据中台:       http://<服务器IP>:8000/docs        ${RESET}"
    echo -e "${GREEN}==============================================================${RESET}"
}

# 10. 实时跟踪日志
show_logs() {
    cd "${ROOT_DIR}"
    docker compose -f "${COMPOSE_FILE}" logs -f "$@"
}

# 11. 停止服务集群
stop_cluster() {
    echo -e "${YELLOW}正在安全停止并清理容器集群...${RESET}"
    cd "${ROOT_DIR}"
    docker compose -f "${COMPOSE_FILE}" down "$@"
    echo -e "${GREEN}✓ 容器集群已停止。持久化数据卷依然安全保存在 docker volumes 中。${RESET}"
}

# 12. 路由子命令
print_banner

case "$1" in
    up|start|"")
        shift || true
        deploy_incremental "$@"
        ;;
    diff|check)
        check_diff
        ;;
    status|ps)
        show_status
        ;;
    logs)
        shift
        show_logs "$@"
        ;;
    stop|down)
        shift
        stop_cluster "$@"
        ;;
    restart)
        shift
        if [ $# -gt 0 ]; then
            echo -e "${YELLOW}正在重启指定微服务: $* ...${RESET}"
            cd "${ROOT_DIR}"
            docker compose -f "${COMPOSE_FILE}" restart "$@"
        else
            echo -e "${YELLOW}正在安全重启全部容器集群...${RESET}"
            stop_cluster
            deploy_incremental
        fi
        ;;
    force)
        shift
        deploy_incremental --force "$@"
        ;;
    clean-cache)
        rm -rf "${CACHE_DIR}"
        echo -e "${GREEN}✓ 已清空部署指纹缓存。${RESET}"
        ;;
    *)
        echo "Quant System 生产增量部署脚本使用说明:"
        echo "  $0                      # 智能增量部署（自动比对代码修改，仅更新被改动的微服务）"
        echo "  $0 up [svc...]          # 智能增量部署，支持指定某一个或几个服务（如 $0 up web-admin）"
        echo "  $0 up --force           # 强制全量重新构建并部署所有服务"
        echo "  $0 check (或 diff)      # 仅比对各微服务代码变动与运行状态，不执行部署"
        echo "  $0 status (或 ps)       # 查看各微服务容器运行状态"
        echo "  $0 logs [svc...]        # 实时查看微服务运行日志"
        echo "  $0 restart [svc...]     # 重启指定服务或全部服务"
        echo "  $0 stop                 # 停止全部微服务容器"
        echo "  $0 clean-cache          # 清空部署指纹缓存"
        exit 1
        ;;
esac
