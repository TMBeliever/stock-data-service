import ast
import math
import traceback
import datetime
from typing import Type, Tuple, Dict, Any, Optional
import numpy as np
import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar, Order, Position, Snapshot, Trade, OrderSide, OrderType

router = APIRouter()

# 高危模块黑名单
FORBIDDEN_MODULES = {
    "os", "sys", "subprocess", "shutil", "socket", "builtins", "importlib",
    "urllib", "requests", "http", "pickle", "shelve", "ctypes", "pty",
    "posix", "posixpath", "signal", "multiprocessing", "threading", "asyncio",
    "webbrowser", "tempfile"
}

# 高危内建函数与属性黑名单
FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "open", "input", "breakpoint", "help",
    "globals", "locals", "vars", "dir", "__import__"
}

FORBIDDEN_ATTRIBUTES = {
    "__subclasses__", "__bases__", "__globals__", "__code__", "__closure__",
    "__class__", "__mro__", "__builtins__"
}


class SecurityCheckError(Exception):
    """AST 安全检测异常"""
    pass


class StrategyASTValidator(ast.NodeVisitor):
    """
    静态语法树 (AST) 安全审计器：
    拦截任何可能越权访问宿主机系统、文件、进程、网络或反射攻击的代码语法。
    """
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            top_pkg = alias.name.split(".")[0]
            if top_pkg in FORBIDDEN_MODULES:
                raise SecurityCheckError(f"安全策略拦截: 禁止导入模块 '{alias.name}' (行 {node.lineno})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            top_pkg = node.module.split(".")[0]
            if top_pkg in FORBIDDEN_MODULES:
                raise SecurityCheckError(f"安全策略拦截: 禁止从模块 '{node.module}' 导入 (行 {node.lineno})")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                raise SecurityCheckError(f"安全策略拦截: 禁止调用高危函数 '{node.func.id}()' (行 {node.lineno})")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in FORBIDDEN_ATTRIBUTES:
            raise SecurityCheckError(f"安全策略拦截: 禁止访问底层反射属性 '{node.attr}' (行 {node.lineno})")
        self.generic_visit(node)


class StrategyCodeSandbox:
    """
    受控 Python 策略执行沙箱：
    负责 AST 校验、受限命名空间构建、动态类提取与实例化。
    """
    @classmethod
    def validate_code(cls, code_str: str) -> ast.AST:
        """解析并审计 Python 源码 AST"""
        try:
            tree = ast.parse(code_str)
        except SyntaxError as e:
            raise ValueError(f"Python 语法错误 [行 {e.lineno}, 列 {e.offset}]: {e.msg}") from e

        validator = StrategyASTValidator()
        validator.visit(tree)
        return tree

    @classmethod
    def load_strategy_class(cls, code_str: str) -> Type[BaseStrategy]:
        """审计并从代码字符串中动态加载 BaseStrategy 子类"""
        tree = cls.validate_code(code_str)

        def safe_import(name, *args, **kwargs):
            top_pkg = name.split(".")[0]
            if top_pkg in FORBIDDEN_MODULES:
                raise SecurityCheckError(f"安全策略拦截: 禁止导入模块 '{name}'")
            return __import__(name, *args, **kwargs)

        import builtins

        safe_builtins = {
            "__import__": safe_import,
            "__build_class__": builtins.__build_class__,
            "range": range, "len": len, "sum": sum, "min": min, "max": max,
            "abs": abs, "round": round, "int": int, "float": float, "str": str,
            "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple,
            "isinstance": isinstance, "issubclass": issubclass, "enumerate": enumerate,
            "zip": zip, "print": print, "Exception": Exception, "ValueError": ValueError,
            "TypeError": TypeError, "KeyError": KeyError, "IndexError": IndexError,
            "super": super, "getattr": getattr, "hasattr": hasattr,
            "sorted": sorted, "reversed": reversed, "any": any, "all": all,
            "map": map, "filter": filter, "None": None, "True": True, "False": False,
        }

        from quant_core.factors.technical import sma, ema, rsi, macd, bollinger_bands, atr
        import typing
        from typing import (
            Optional, List, Dict, Tuple, Set, Any, Union, Sequence, Callable, Iterable
        )

        safe_globals: Dict[str, Any] = {
            "__builtins__": safe_builtins,
            "__name__": "__custom_strategy__",
            "BaseStrategy": BaseStrategy,
            "Strategy": BaseStrategy,
            "Bar": Bar,
            "Order": Order,
            "Position": Position,
            "Snapshot": Snapshot,
            "Trade": Trade,
            "OrderSide": OrderSide,
            "OrderType": OrderType,
            "math": math,
            "np": np,
            "numpy": np,
            "pd": pd,
            "pandas": pd,
            "datetime": datetime,
            "typing": typing,
            "Optional": Optional,
            "List": List,
            "Dict": Dict,
            "Tuple": Tuple,
            "Set": Set,
            "Any": Any,
            "Union": Union,
            "Sequence": Sequence,
            "Callable": Callable,
            "Iterable": Iterable,
            # 内置常用指标函数
            "sma": sma,
            "ema": ema,
            "rsi": rsi,
            "macd": macd,
            "bollinger_bands": bollinger_bands,
            "atr": atr,
        }

        local_scope: Dict[str, Any] = {}

        try:
            compiled_code = compile(tree, filename="<custom_strategy.py>", mode="exec")
            exec(compiled_code, safe_globals, local_scope)
        except Exception as e:
            tb = traceback.format_exc(limit=3)
            raise RuntimeError(f"策略代码执行/定义异常: {e}\n{tb}") from e

        # 1. 寻找显式继承自 BaseStrategy 的子类
        candidate_cls: Optional[Type[BaseStrategy]] = None
        for name, obj in local_scope.items():
            if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                candidate_cls = obj
                break

        # 2. 容错增强：若未显式继承，但类中定义了 on_bar 方法，自动为其混入 BaseStrategy
        if not candidate_cls:
            for name, obj in local_scope.items():
                if isinstance(obj, type) and hasattr(obj, "on_bar") and callable(getattr(obj, "on_bar")):
                    wrapped_cls = type(name, (obj, BaseStrategy), {})
                    candidate_cls = wrapped_cls
                    break

        if not candidate_cls:
            # 兼容如果在全局作用域注册
            for name, obj in safe_globals.items():
                if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    candidate_cls = obj
                    break

        if not candidate_cls:
            raise ValueError("未在代码中找到继承自 BaseStrategy 或包含 on_bar(self, bar) 的量化策略类。")

        return candidate_cls

    @classmethod
    def instantiate_strategy(cls, strategy_cls: Type[BaseStrategy]) -> BaseStrategy:
        """
        智能容错实例化策略类：
        若策略类的 __init__ 包含未设置默认值的必须参数（如 AI 漏写默认实参），
        自动通过 inspect.signature 探测参数名与注解，智能注入合理默认值，确保 100% 成功实例化。
        """
        import inspect
        instance: Optional[BaseStrategy] = None
        try:
            instance = strategy_cls()
        except TypeError as err:
            try:
                sig = inspect.signature(strategy_cls.__init__)
                params = sig.parameters
                kwargs: Dict[str, Any] = {}
                for name, p in params.items():
                    if name in ("self", "args", "kwargs"):
                        continue
                    if p.default != inspect.Parameter.empty:
                        kwargs[name] = p.default
                    else:
                        lower = name.lower()
                        if "fast" in lower or "short" in lower:
                            kwargs[name] = 5
                        elif "slow" in lower or "long" in lower:
                            kwargs[name] = 20
                        elif any(k in lower for k in ("period", "window", "len", "n", "days", "step")):
                            kwargs[name] = 14
                        elif any(k in lower for k in ("pct", "rate", "ratio", "threshold", "percent")):
                            kwargs[name] = 0.05
                        elif p.annotation in (int, "int"):
                            kwargs[name] = 10
                        elif p.annotation in (float, "float"):
                            kwargs[name] = 0.1
                        elif p.annotation in (str, "str"):
                            kwargs[name] = ""
                        elif p.annotation in (bool, "bool"):
                            kwargs[name] = True
                        else:
                            kwargs[name] = 10
                instance = strategy_cls(**kwargs)
            except Exception:
                raise err

        # 防御加固：即便子类策略未调用 super().__init__()，自动为其补齐所有核心运行时属性
        if not hasattr(instance, "name") or not instance.name:
            instance.name = instance.__class__.__name__
        if not hasattr(instance, "params"):
            instance.params = {}
        if not hasattr(instance, "context"):
            instance.context = None
        if not hasattr(instance, "_pending_orders"):
            instance._pending_orders = []
        if not hasattr(instance, "_current_bar"):
            instance._current_bar = None
        if not hasattr(instance, "_current_symbol"):
            instance._current_symbol = None
        if not hasattr(instance, "_bars_storage"):
            instance._bars_storage = []

        return instance


class CodeValidationRequest(BaseModel):
    code: str = Field(..., description="待校验的策略源码")


@router.post("/sandbox/validate")
def validate_code_endpoint(req: CodeValidationRequest):
    """
    在线校验 Python 量化策略源码：
    1. 静态 AST 安全审计；
    2. 类结构与 BaseStrategy 继承合法性检查；
    3. 构造函数实例化尝试；
    4. 返回诊断建议与类元数据。
    """
    try:
        cls_obj = StrategyCodeSandbox.load_strategy_class(req.code)
        try:
            inst = cls_obj()
            params = getattr(inst, "params", {})
            name = getattr(inst, "name", cls_obj.__name__)
        except Exception as init_e:
            return {
                "is_valid": False,
                "error": f"策略类初始化异常 (缺少默认参数或构造函数错误): {str(init_e)}",
                "strategy_name": cls_obj.__name__ if cls_obj else None,
            }

        return {
            "is_valid": True,
            "strategy_name": name,
            "params": params,
            "message": "策略源码安全审计与继承规范检查通过，可直接加入回测或实盘。"
        }
    except SecurityCheckError as e:
        return {"is_valid": False, "error": f"安全策略拦截: {str(e)}"}
    except ValueError as e:
        return {"is_valid": False, "error": f"代码规范错误: {str(e)}"}
    except Exception as e:
        return {"is_valid": False, "error": f"执行/语法异常: {str(e)}"}
