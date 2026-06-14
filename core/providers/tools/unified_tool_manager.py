"""统一工具管理器"""

from typing import Dict, List, Optional, Any
from config.logger import setup_logging
from plugins_func.register import Action, ActionResponse
from .base import ToolType, ToolDefinition, ToolExecutor


class ToolManager:
    """统一工具管理器，管理所有类型的工具"""

    def __init__(self, conn):
        self.conn = conn
        self.logger = setup_logging()
        self.executors: Dict[ToolType, ToolExecutor] = {}
        self._cached_tools: Optional[Dict[str, ToolDefinition]] = None
        self._cached_function_descriptions: Optional[List[Dict[str, Any]]] = None

    def register_executor(self, tool_type: ToolType, executor: ToolExecutor):
        """注册工具执行器"""
        self.executors[tool_type] = executor
        self._invalidate_cache()
        self.logger.info(f"注册工具执行器: {tool_type.value}")

    def _invalidate_cache(self):
        """使缓存失效"""
        self._cached_tools = None
        self._cached_function_descriptions = None

    def get_all_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有工具定义"""
        if self._cached_tools is not None:
            return self._cached_tools

        all_tools = {}
        for tool_type, executor in self.executors.items():
            try:
                tools = executor.get_tools()
                for name, definition in tools.items():
                    if name in all_tools:
                        self.logger.warning(f"工具名称冲突: {name}")
                    all_tools[name] = definition
            except Exception as e:
                self.logger.error(f"获取{tool_type.value}工具时出错: {e}")

        self._cached_tools = all_tools
        return all_tools

    def get_function_descriptions(self) -> List[Dict[str, Any]]:
        """获取所有工具的函数描述（OpenAI格式）"""
        if self._cached_function_descriptions is not None:
            return self._cached_function_descriptions

        descriptions = []
        tools = self.get_all_tools()
        for tool_definition in tools.values():
            descriptions.append(tool_definition.description)

        self._cached_function_descriptions = descriptions
        return descriptions

    def has_tool(self, tool_name: str) -> bool:
        """检查是否存在指定工具"""
        tools = self.get_all_tools()
        return tool_name in tools

    def get_tool_type(self, tool_name: str) -> Optional[ToolType]:
        """获取工具类型"""
        tools = self.get_all_tools()
        tool_def = tools.get(tool_name)
        return tool_def.tool_type if tool_def else None

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行工具调用"""
        try:
            # 严格意图守卫：强控 generate_image 被错误调用的场景
            try:
                name_lower = str(tool_name).lower()
                if "generate_image" in name_lower:
                    q = str(
                        arguments.get("question")
                        or arguments.get("text")
                        or arguments.get("prompt")
                        or ""
                    )
                    
                    # 尝试从对话历史中获取用户真正的原始输入
                    original_text = ""
                    try:
                        if hasattr(self, "conn") and hasattr(self.conn, "dialogue"):
                            for msg in reversed(self.conn.dialogue.dialogue):
                                if msg.role == "user":
                                    original_text = msg.content
                                    break
                    except Exception as e:
                        pass
                    
                    # 如果有历史原始文本，用原始文本做判定；否则退化使用参数 q
                    check_text = original_text if original_text else q
                    ft = check_text.replace(" ", "")
                    
                    # 1. 拦截应该归属于“拍照”的动作
                    if "拍照" in ft or "打开摄像头" in ft or ("拍摄" in ft and "照片" in ft):
                        self.logger.info("守卫：拍照意图拒绝调用 generate_image，尝试改走设备摄像头")
                        # 若设备摄像头工具存在，则直接调用之
                        try:
                            cam_alias = None
                            for n in self.get_supported_tool_names():
                                if "self_camera_take_photo" in n or "self.camera.take_photo" in n:
                                    cam_alias = n
                                    break
                            if cam_alias:
                                args = {"question": original_text or q}
                                return await self.execute_tool(cam_alias, args)
                        except Exception:
                            pass
                        return ActionResponse(action=Action.NOTFOUND, response="设备摄像头暂未就绪，无法拍照哦")

                    # 2. 如果文本实际上连【生成+图片】都没有，强行阻断生图请求以防大模型乱猜
                    if "生成" not in ft or "图片" not in ft:
                        self.logger.info(f"守卫：文本要求不满足严格条件【生成……图片】，强行中止生成图片 (判定文本: {check_text})")
                        # 返回普通的对话响应要求大模型改用纯文字回答
                        return ActionResponse(action=Action.REQLLM, result="由于用户没有明确说“生成...图片”，请告知用户你不会生成图片，并询问对方还需要什么帮助。")
            except Exception:
                pass
            # 标记工具执行中，避免连接在长时间工具运行期间被空闲超时关闭
            try:
                setattr(self.conn, "_tool_running", True)
            except Exception:
                pass
            # 查找工具类型
            tool_type = self.get_tool_type(tool_name)
            if not tool_type:
                return ActionResponse(
                    action=Action.NOTFOUND,
                    response=f"工具 {tool_name} 不存在",
                )

            # 获取对应的执行器
            executor = self.executors.get(tool_type)
            if not executor:
                return ActionResponse(
                    action=Action.ERROR,
                    response=f"工具类型 {tool_type.value} 的执行器未注册",
                )

            # 执行工具
            self.logger.info(
                f"执行工具: {tool_name}，参数: {arguments} | tool_type={tool_type.value} executor={executor.__class__.__name__}"
            )
            result = await executor.execute(self.conn, tool_name, arguments)

            # [双重保险] 防止 executor 执行后返回的是一个未 await 的 coroutine
            import asyncio
            import inspect
            if asyncio.iscoroutine(result) or inspect.isawaitable(result):
                self.logger.warning(f"检测到工具 {tool_name} 返回了未等待的协程，正在强制 await...")
                try:
                    result = await result
                except TypeError:
                    pass

            self.logger.debug(f"工具执行结果: {result}")
            return result

        except Exception as e:
            self.logger.error(f"执行工具 {tool_name} 时出错: {e}")
            return ActionResponse(action=Action.ERROR, response=str(e))
        finally:
            # 无论成功失败，取消保护标记
            try:
                setattr(self.conn, "_tool_running", False)
                if hasattr(self.conn, "mark_active"):
                    self.conn.mark_active()
            except Exception:
                pass

    def get_supported_tool_names(self) -> List[str]:
        """获取所有支持的工具名称"""
        tools = self.get_all_tools()
        return list(tools.keys())

    def refresh_tools(self):
        """刷新工具缓存"""
        self._invalidate_cache()
        self.logger.info("工具缓存已刷新")

    def get_tool_statistics(self) -> Dict[str, int]:
        """获取工具统计信息"""
        stats = {}
        for tool_type, executor in self.executors.items():
            try:
                tools = executor.get_tools()
                stats[tool_type.value] = len(tools)
            except Exception as e:
                self.logger.error(f"获取{tool_type.value}工具统计时出错: {e}")
                stats[tool_type.value] = 0
        return stats
