import sys
import os

# 确保 packages/quant-core/src 在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "packages", "quant-core", "src")))

from quant_core.run_backtest import main

if __name__ == "__main__":
    main()
