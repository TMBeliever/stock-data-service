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

        # 寻找定义的 BaseStrategy 子类
        candidate_cls: Optional[Type[BaseStrategy]] = None
        for name, obj in local_scope.items():
            if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                candidate_cls = obj
                break

        if not candidate_cls:
            # 兼容如果在全局作用域注册
            for name, obj in safe_globals.items():
                if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    candidate_cls = obj
                    break

        if not candidate_cls:
            raise ValueError("未在代码中找到继承自 BaseStrategy 的策略类，请确保策略类继承自 BaseStrategy。")

        return candidate_cls


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
