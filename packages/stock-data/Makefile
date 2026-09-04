.PHONY: run start test test-live test-all status clean docs sync reconcile

# 默认运行服务
run: start

start:
	@./start.sh

# 默认运行本地/离线快速单元测试 (跳过 live 外部网络请求，保障 CI/CD 极速稳定)
test:
	@./.venv/bin/pytest -v -m "not live"

# 运行真实外部接口网络集成测试
test-live:
	@./.venv/bin/pytest -v -m "live"

# 运行全量测试
test-all:
	@./.venv/bin/pytest -v

# 查看当前 50G 磁盘水位
status:
	@./.venv/bin/python cli.py disk-check

# 手动执行 LRU 清理
clean:
	@./.venv/bin/python cli.py evict

# 物理 Parquet 与 SQLite 元数据对齐
reconcile:
	@./.venv/bin/python cli.py reconcile

# 重新导出最新 API 接口文档
docs:
	@./.venv/bin/python cli.py gen-docs

# 盘后一键增量同步与预热
sync:
	@./.venv/bin/python cli.py sync


