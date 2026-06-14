"""服务端插件工具执行器"""

from typing import Dict, Any
import inspect
import asyncio
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import all_function_registry, Action, ActionResponse
from config.logger import setup_logging
import time


class ServerPluginExecutor(ToolExecutor):
    """服务端插件工具执行器"""

    def __init__(self, conn):
        self.conn = conn
        self.config = conn.config
        self.logger = setup_logging()

    async def execute(
        self, conn, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行服务端插件工具"""
        t0 = int(time.time() * 1000)
        func_item = all_function_registry.get(tool_name)
        if not func_item:
            return ActionResponse(
                action=Action.NOTFOUND, response=f"插件函数 {tool_name} 不存在"
            )

        try:
            func = func_item.func

            # 是否显式需要 conn 参数（根据签名或类型）
            sig = inspect.signature(func)
            need_conn = "conn" in sig.parameters
            # 兼容旧式 ToolType 判断
            func_type = getattr(func_item, "type", None)
            if func_type is not None and getattr(func_type, "code", None) in [3, 4, 5]:
                need_conn = True or need_conn

            try:
                origin = inspect.getsourcefile(func) or inspect.getfile(func)
            except Exception:
                origin = "<unknown>"

            self.logger.info(
                f"[plugin-exec] => {tool_name} | origin={origin} need_conn={need_conn} args={arguments}"
            )

            # 执行函数
            if asyncio.iscoroutinefunction(func):
                if need_conn:
                    result = await func(conn, **arguments)
                else:
                    result = await func(**arguments)
            else:
                if need_conn:
                    result = func(conn, **arguments)
                else:
                    result = func(**arguments)

                # 如果同步函数返回了 awaitable (如 coroutine)，则 await 它
                if inspect.isawaitable(result):
                    result = await result

            dt = int(time.time() * 1000) - t0
            try:
                result_action = getattr(result, "action", None)
            except Exception:
                result_action = None
            self.logger.info(
                f"[plugin-exec] <= {tool_name} | dt={dt}ms action={result_action}"
            )

            return result

        except Exception as e:
            dt = int(time.time() * 1000) - t0
            self.logger.error(f"[plugin-exec] !! {tool_name} error after {dt}ms: {e}")
            return ActionResponse(
                action=Action.ERROR,
                response=str(e),
            )

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有注册的服务端插件工具"""
        tools = {}

        # 获取必要的函数
        necessary_functions = ["handle_exit_intent", "get_lunar"]

        # 获取配置中的函数
        config_functions = self.config["Intent"][
            self.config["selected_module"]["Intent"]
        ].get("functions", [])

        # 转换为列表
        if not isinstance(config_functions, list):
            try:
                config_functions = list(config_functions)
            except TypeError:
                config_functions = []

        # 合并所有需要的函数
        all_required_functions = list(set(necessary_functions + config_functions))

        for func_name in all_required_functions:
            func_item = all_function_registry.get(func_name)
            if func_item:
                tools[func_name] = ToolDefinition(
                    name=func_name,
                    description=func_item.description,
                    tool_type=ToolType.SERVER_PLUGIN,
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的服务端插件工具"""
        return tool_name in all_function_registry
