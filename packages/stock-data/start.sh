#!/usr/bin/env bash
set -e

# 进入当前脚本所在目录
cd "$(dirname "$0")"

# 1. 如果环境不存在，自动通过 uv 创建并安装
if [ ! -d ".venv" ]; then
    echo "⚙️ 未检测到虚拟环境，正在自动初始化..."
    if command -v uv &> /dev/null; then
        uv venv --python python3.12
        uv pip install -e . --default-index https://mirrors.aliyun.com/pypi/simple/
    else
        python3 -m venv .venv
        ./.venv/bin/pip install -e . -i https://mirrors.aliyun.com/pypi/simple/
    fi
fi

# 2. 如果是初次运行，自动初始化数据库与核心指数
if [ ! -f "data/metadata/meta.db" ]; then
    echo "📦 正在初次初始化元数据底座与核心资产池..."
    ./.venv/bin/python cli.py init
fi

echo ""
echo "========================================================"
echo "  🚀 全球股票数据服务启动成功！"
echo "  📖 在线接口调试文档: http://localhost:8000/docs"
echo "  💾 50GB 存储监控接口: http://localhost:8000/api/v1/system/storage"
echo "  💡 提示: 按 Ctrl + C 即可随时停止服务"
echo "========================================================"
echo ""

# 3. 延时 1 秒自动在 Mac 默认浏览器中打开接口文档
(sleep 1.2 && open "http://localhost:8000/docs" 2>/dev/null) &

# 4. 启动主服务
exec ./.venv/bin/python service/app.py
