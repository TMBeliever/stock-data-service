import inspect
import json
import asyncio
from typing import Callable, Dict, Any, Optional, List, Union
from ai_core.models import ToolDefinition

class BaseTool:
    """标准通用工具抽象基类"""
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        category: str = "general",
        func: Optional[Callable] = None
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.category = category
        self._func = func

    def __call__(self, *args, **kwargs):
        """支持直接像普通函数一样调用"""
        if self._func is None:
            raise NotImplementedError(f"Tool {self.name} has no executable implementation")
        return self._func(*args, **kwargs)

    async def execute(self, on_progress: Optional[Callable[[str], Any]] = None, **kwargs) -> Any:
        """执行工具，兼容同步与异步函数，并支持传入流式进度回调"""
        if self._func is None:
            raise NotImplementedError(f"Tool {self.name} has no executable implementation")
        
        # 若工具实现函数声明了 on_progress 参数，则注入回调
        sig = inspect.signature(self._func)
        if "on_progress" in sig.parameters and on_progress is not None:
            kwargs["on_progress"] = on_progress

        if inspect.iscoroutinefunction(self._func):
            return await self._func(**kwargs)
        else:
            # 在线程池中执行同步阻塞函数，避免卡住异步事件循环
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: self._func(**kwargs))

    def to_tool_definition(self) -> ToolDefinition:
        """转换为通用大模型 ToolDefinition 标准对象"""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters
        )

def _py_type_to_json_schema(py_type) -> str:
    """简易类型映射"""
    if py_type in (str, Optional[str]):
        return "string"
    elif py_type in (int, Optional[int]):
        return "integer"
    elif py_type in (float, Optional[float]):
        return "number"
    elif py_type in (bool, Optional[bool]):
        return "boolean"
    elif py_type in (list, List, Optional[list], Optional[List]):
        return "array"
    elif py_type in (dict, Dict, Optional[dict], Optional[Dict]):
        return "object"
    return "string"

def tool(name: Optional[str] = None, description: Optional[str] = None, category: str = "general"):
    """
    函数装饰器：自动将 Python 函数包装为 BaseTool 并推导 JSON Schema
    """
    def decorator(fn: Callable) -> BaseTool:
        tool_name = name or fn.__name__
        tool_desc = (description or fn.__doc__ or "").strip()
        
        sig = inspect.signature(fn)
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls", "on_progress"):
                continue
            
            p_type = param.annotation if param.annotation != inspect.Parameter.empty else str
            schema_type = _py_type_to_json_schema(p_type)
            prop_def: Dict[str, Any] = {"type": schema_type}

            if param.default == inspect.Parameter.empty:
                required.append(param_name)
            else:
                prop_def["default"] = param.default

            properties[param_name] = prop_def

        parameters = {
            "type": "object",
            "properties": properties,
        }
        if required:
            parameters["required"] = required

        return BaseTool(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            category=category,
            func=fn
        )
    return decorator

class ToolRegistry:
    """
    通用工具注册表：
    支持多领域分类挂载、动态按需筛选与生命周期调度
    """
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool_instance: BaseTool) -> None:
        """注册工具实例"""
        self._tools[tool_instance.name] = tool_instance

    def register_function(
        self,
        fn: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: str = "general"
    ) -> BaseTool:
        """注册普通 Python 函数为工具"""
        tool_obj = tool(name=name, description=description, category=category)(fn)
        self.register(tool_obj)
        return tool_obj

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> List[BaseTool]:
        """列出工具列表，支持按分类过滤"""
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def to_definitions(self, category: Optional[str] = None) -> List[ToolDefinition]:
        """导出为用于大模型上下文绑定的 ToolDefinition 列表"""
        return [t.to_tool_definition() for t in self.list_tools(category)]

    def copy(self) -> "ToolRegistry":
        """创建当前注册表的浅拷贝副本"""
        cloned = ToolRegistry()
        cloned._tools = dict(self._tools)
        return cloned

    def merge(self, other: "ToolRegistry") -> "ToolRegistry":
        """将另一个注册表的工具合并入当前注册表"""
        self._tools.update(other._tools)
        return self

    async def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        on_progress: Optional[Callable[[str], Any]] = None
    ) -> Any:
        """执行指定工具并返回原生结果，支持传入流式进度回调"""
        tool_obj = self.get_tool(name)
        if not tool_obj:
            raise ValueError(f"Tool '{name}' not found in registry")
        return await tool_obj.execute(on_progress=on_progress, **arguments)
