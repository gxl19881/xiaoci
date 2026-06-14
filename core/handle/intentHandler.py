import json
import uuid
import asyncio
from core.utils.dialogue import Message
from core.providers.tts.dto.dto import ContentType
from core.handle.helloHandle import checkWakeupWords
from plugins_func.register import Action, ActionResponse
from core.handle.sendAudioHandle import send_stt_message
from core.utils.util import remove_punctuation_and_length
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType

TAG = __name__


async def handle_user_intent(conn, text):
    # Ensure any pending silence trigger is cancelled, as we are now handling a new intent
    try:
        t = getattr(conn, "_silence_trigger_task", None)
        if t and not t.done():
            t.cancel()
    except Exception:
        pass

    # 预处理输入文本，处理可能的JSON格式
    try:
        if text.strip().startswith('{') and text.strip().endswith('}'):
            parsed_data = json.loads(text)
            if isinstance(parsed_data, dict) and "content" in parsed_data:
                text = parsed_data["content"]  # 提取content用于意图分析
                conn.current_speaker = parsed_data.get("speaker")  # 保留说话人信息
    except (json.JSONDecodeError, TypeError):
        pass

    # 优先级直达（最高优先）：拍照/拍张/开始拍照 => 直接走设备MCP摄像头工具，避免被图像生成类插件抢占
    # 放在所有意图分支之前，确保不被LLM重写为 generate_image
    _, filtered_text = remove_punctuation_and_length(text)

    # 快捷进入英语对话练习
    enter_keywords = ("英语对话练习", "练习英语对话", "英语外教", "扮演英语老师", "启动英语对话")
    if any(k in filtered_text for k in enter_keywords):
        conn.logger.bind(tag=TAG).info(f"识别到主动开启英语对话练习意图: {filtered_text}")
        from plugins_func.functions.change_role import change_role
        await send_stt_message(conn, text)
        change_role(conn, "英语老师", "Lily")
        
        conn.sentence_id = str(uuid.uuid4().hex)
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.FIRST, content_type=ContentType.ACTION)
        )
        msg_text = "我已经变身英语老师啦，现在为您打开摄像头拍课本。"
        conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=msg_text)
        conn.tts.tts_text_queue.put(
            TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION)
        )
        conn.dialogue.put(Message(role="assistant", content=msg_text))
        
        # 直接拉起设备的拍照动作 (模拟用户说了"开始拍照")
        try:
            await _try_device_camera_direct(conn, "开始拍照", original_text="开始拍照")
        except Exception as e:
            conn.logger.bind(tag=TAG).error(f"英语对话直接拉起拍照失败: {e}")
        
        return True

    # 对话练习"结束练习"处理（在拍照检测之前，确保优先级）
    if filtered_text in ("结束练习", "结束对话练习", "结束对话"):
        if getattr(conn, "dialogue_practice", {}).get("active"):
            conn.logger.bind(tag=TAG).info("识别到结束对话练习命令")
            await send_stt_message(conn, text)
            original_prompt = conn.dialogue_practice.get("original_prompt", "")
            conn.dialogue_practice = {
                "active": False, "content": "", "system_prompt": "", "original_prompt": ""
            }
            conn.dialogue = Dialogue()
            if original_prompt:
                conn.change_system_prompt(original_prompt)
            speak_txt(conn, "好的，对话练习结束了，有什么需要帮忙的随时叫我。")
            return True

    # 对话练习"继续/再来"恢复处理
    resume_keywords = ("再来一次", "继续练习", "再练一次", "继续对话练习", "进行对话练习",
                       "我要进行对话练习", "我要练习对话", "对话练习", "再来一遍")
    if filtered_text in resume_keywords:
        practice = getattr(conn, "dialogue_practice", {})
        if practice.get("active") and practice.get("content"):
            conn.logger.bind(tag=TAG).info(f"识别到恢复对话练习命令: {filtered_text}")
            await send_stt_message(conn, text)
            conn.client_abort = False
            # 确保英语教师prompt和对话内容在当前dialogue中
            conn.dialogue.update_system_message(practice["system_prompt"])
            conn.prompt = practice["system_prompt"]
            conn.dialogue.put(Message(role="user", content=filtered_text))
            # 引导LLM恢复对话练习
            resume_prompt = (
                f"用户说「{filtered_text}」。\n"
                f"【系统严格指令：请立刻根据之前识别的对话剧本来原继续进行口语发音检查练习。】\n"
                f"对话内容如下：\n{practice['content']}\n"
                f"规则：核对用户的发音。准确则表扬并给出下一句；不准确则指出错误要求重读。不得闲聊脱离剧本。"
            )
            conn.dialogue.put(Message(role="assistant", content=resume_prompt))
            conn.sentence_id = str(uuid.uuid4().hex)
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.FIRST, content_type=ContentType.ACTION)
            )
            conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail="好的，我们继续练习，请选择你的角色开始对话吧。")
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION)
            )
            conn.dialogue.put(Message(role="assistant", content="好的，我们继续练习，请选择你的角色开始对话吧。"))
            return True

    try:
        if await _try_device_camera_direct(conn, filtered_text, original_text=text):
            return True
    except Exception:
        # 直达失败则回落到原有流程
        pass

    # 检查是否有明确的退出命令
    if await check_direct_exit(conn, filtered_text):
        return True

    # 自定义打开百度浏览器命令
    if filtered_text in ["生成一个边长为10的立方体", "生成立方体", "画一个立方体", "生成一个边长为十的立方体"]:
        conn.logger.bind(tag=TAG).info("识别到生成立方体 intent")
        try:
            from plugins_func.functions.show_3d_cube import show_cube
            await show_cube(conn, 10)
        except Exception as e:
            conn.logger.bind(tag=TAG).error(f"生成立方体失败: {e}")
        return True

    if filtered_text in ["打开百度浏览器", "打开百度", "打开百度搜索"]:
        conn.logger.bind(tag=TAG).info("识别到打开百度浏览器 intent")
        try:
            from plugins_func.functions.open_baidu_browser import display_baidu
            await display_baidu(conn)
        except Exception as e:
            conn.logger.bind(tag=TAG).error(f"打开百度浏览器失败: {e}")
        return True


    # 检查是否是唤醒词
    if await checkWakeupWords(conn, filtered_text):
        return True

    if conn.intent_type == "function_call":
        # 使用支持function calling的聊天方法,不再进行意图分析
        return False
    # 使用LLM进行意图分析
    intent_result = await analyze_intent_with_llm(conn, text)
    if not intent_result:
        return False
    # 会话开始时生成sentence_id
    conn.sentence_id = str(uuid.uuid4().hex)
    # 处理各种意图
    return await process_intent_result(conn, intent_result, text)


async def _try_device_camera_direct(conn, filtered_text: str, original_text: str) -> bool:
    """当识别到拍照相关口令且设备MCP已就绪时，直接调用设备摄像头工具。

    命中条件：
    - 文本包含："拍照"、"拍张"、"拍个"、"开始拍照"、"拍一下" 等关键词
    - 客户端声明支持MCP，且设备端MCP工具已ready
    - 设备工具集中存在包含 take_photo 的工具（如 self_camera_take_photo）
    """
    try:
        text = (filtered_text or "").strip()
        if not text:
            return False
        # 关键字匹配（严格遵循新规则：必须完全匹配要求中的关键字）
        valid_cam = False
        if "拍照" in text or "打开摄像头" in text:
            valid_cam = True
        elif "拍摄" in text and "照片" in text:
            valid_cam = True
        elif any(k in text for k in ["合并", "merge", "Merge", "拍第一张", "拍第二张", "共拍两张", "开始拍照", "看看这是什么", "识别"]):
            valid_cam = True
            
        if not valid_cam:
            return False

        # 检查MCP能力与就绪状态
        if not getattr(conn, "features", None) or not conn.features.get("mcp"):
            conn.logger.bind(tag=TAG).warning("直达失败：客户端未声明MCP特性")
            return False
        if not hasattr(conn, "mcp_client") or conn.mcp_client is None:
            conn.logger.bind(tag=TAG).warning("直达失败：MCP客户端未初始化")
            return False
        try:
            is_ready = await conn.mcp_client.is_ready()
        except Exception:
            is_ready = False
        
        # 查找设备端摄像头工具（名称中包含 take_photo 即可）
        cam_tool = None
        if is_ready:
            try:
                for name in (conn.mcp_client.tools or {}).keys():
                    if "take_photo" in str(name).lower():
                        cam_tool = name
                        break
            except Exception:
                cam_tool = None
        else:
            # 若未就绪但支持MCP，尝试盲猜工具名
            conn.logger.bind(tag=TAG).warning("MCP未就绪，尝试盲猜摄像头工具名")
            cam_tool = "self.camera.take_photo"

        if not cam_tool:
            conn.logger.bind(tag=TAG).warning("直达失败：未找到 take_photo 工具")
            return False

        # 先回显文本（与常规流程一致）
        await send_stt_message(conn, original_text)
        conn.client_abort = False

        # 调用设备端摄像头工具：传入问题文本，避免视觉接口缺失question
        try:
            # 智能解析张数 (支持 "拍X张", "合并X张", "X张照片")
            import re
            count = 1
            chk_text = (original_text or "").replace(" ", "")
            
            # 中文数字映射
            num_map = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
            
            # 使用正则优先提取明确的数量描述
            match = re.search(r"(?:拍|合并)(\d+|[一二两三四五六七八九十])张", chk_text)
            if not match:
                 match = re.search(r"(\d+|[一二两三四五六七八九十])张照片", chk_text)
            
            if match:
                num_str = match.group(1)
                if num_str.isdigit():
                    val = int(num_str)
                    if val > 0: count = val
                elif num_str in num_map:
                    count = num_map[num_str]
            
            # 限制合理范围
            if count > 10: count = 10

            # 检测合并意图，若为合并则通过 operation 参数告知设备端跳过预览
            operation = "analyze"
            if "合并" in chk_text or "merge" in chk_text.lower():
                operation = "merge_and_analyze"
                # [Updated] 不再强制重置 count=1，允许用户指定合并数量 (e.g. 合并3张 -> count=3)
                # 仅当未解析出有效数量(默认为1)时，若有合并意图，可考虑默认为2？
                # 暂时保持 count 原值 (若用户只说"合并照片", count=1; 若"合并3张", count=3)
                if count == 1 and ("两" in chk_text or "2" in chk_text): # 简单兜底
                     count = 2

            # 使用统一工具管理器调度，确保统一日志与容错
            args = {"question": original_text or filtered_text or "", "count": count, "operation": operation}
            conn.logger.bind(tag=TAG).info(f"拍照直达触发：调用 {cam_tool} count={count} op={operation}")
            
            # 若未就绪，直接使用 DeviceMCPExecutor 执行（绕过 ToolManager 的类型查找）
            if not is_ready:
                from core.providers.tools.base import ToolType
                executor = conn.func_handler.tool_manager.executors.get(ToolType.DEVICE_MCP)
                if executor:
                    result = await executor.execute(conn, cam_tool, args)
                else:
                    conn.logger.bind(tag=TAG).error("直达失败：未找到 DeviceMCPExecutor")
                    return False
            else:
                result = await conn.func_handler.tool_manager.execute_tool(cam_tool, args)
        except Exception as e:
            conn.logger.bind(tag=TAG).error(f"拍照直达执行异常: {e}")
            return False

        # 统一处理返回（设备MCP执行器会负责播报视觉结果/保活）
        if isinstance(result, ActionResponse):
            if result.action in [Action.RESPONSE, Action.ERROR, Action.NOTFOUND]:
                # 非视觉播报类：兜底播报文本
                text_out = result.response or result.result or ""
                if text_out:
                    speak_txt(conn, text_out)
                return True
            # 对于 Action.REQLLM，由后续LLM继续处理
            return True

        return True
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"拍照直达未知异常: {e}")
        return False


async def check_direct_exit(conn, text):
    """检查是否有明确的退出命令"""
    _, text = remove_punctuation_and_length(text)
    cmd_exit = conn.cmd_exit
    for cmd in cmd_exit:
        if text == cmd:
            conn.logger.bind(tag=TAG).info(f"识别到明确的退出命令: {text}")
            await send_stt_message(conn, text)
            await conn.close()
            return True
    return False


async def analyze_intent_with_llm(conn, text):
    """使用LLM分析用户意图"""
    if not hasattr(conn, "intent") or not conn.intent:
        conn.logger.bind(tag=TAG).warning("意图识别服务未初始化")
        return None

    # 对话历史记录
    dialogue = conn.dialogue
    try:
        intent_result = await conn.intent.detect_intent(conn, dialogue.dialogue, text)
        return intent_result
    except Exception as e:
        conn.logger.bind(tag=TAG).error(f"意图识别失败: {str(e)}")

    return None


async def process_intent_result(conn, intent_result, original_text):
    """处理意图识别结果"""
    try:
        # 尝试将结果解析为JSON
        intent_data = json.loads(intent_result)

        # 检查是否有function_call
        if "function_call" in intent_data:
            # 直接从意图识别获取了function_call
            conn.logger.bind(tag=TAG).debug(
                f"检测到function_call格式的意图结果: {intent_data['function_call']['name']}"
            )
            function_name = intent_data["function_call"]["name"]

            # 守卫：若语音包含拍照意图关键词，则强制走设备摄像头直达，避免被 generate_image 抢占
            try:
                _, ft = remove_punctuation_and_length(original_text)
                camera_keywords = ["开始拍照", "拍照", "拍张", "拍个", "拍一下", "拍一张", "拍个照", "合并"]
                if any(k in ft for k in camera_keywords):
                    if await _try_device_camera_direct(conn, ft, original_text=original_text):
                        conn.logger.bind(tag=TAG).info("守卫触发：拍照意图优先走设备MCP摄像头，跳过LLM函数调用")
                        return True
            except Exception:
                pass

            # 额外守卫：严控 generate_image 的准入条件
            if "generate_image" in function_name.lower():
                try:
                    _, ft = remove_punctuation_and_length(original_text)
                    
                    # 1. 如果包含拍照指令，拦截生图，改为走设备相机通道
                    if "拍照" in ft or "打开摄像头" in ft or ("拍摄" in ft and "照片" in ft):
                        conn.logger.bind(tag=TAG).info("阻止 generate_image：发现拍照意图，交由设备摄像头处理")
                        if await _try_device_camera_direct(conn, ft, original_text=original_text):
                            return True
                        conn.logger.bind(tag=TAG).warning("设备摄像头不可用，已拦截 generate_image")
                        speak_txt(conn, "设备摄像头暂时不可用，无法拍照。")
                        return True
                    
                    # 2. 如果没有任何明确的生图指令，强行拦截生图尝试，回退为普通对话
                    if "生成" not in ft or "图片" not in ft:
                        conn.logger.bind(tag=TAG).info("阻止 generate_image：未在语句中发现【生成...图片】的明确关键词，回退为普通文本对话")
                        return False # 返回False则放弃工具调用，直接进入正常聊天（大模型用文字回）
                except Exception:
                    pass
            if function_name == "continue_chat":
                return False

            if function_name == "result_for_context":
                await send_stt_message(conn, original_text)
                conn.client_abort = False
                
                def process_context_result():
                    conn.dialogue.put(Message(role="user", content=original_text))
                    
                    from core.utils.current_time import get_current_time_info

                    current_time, today_date, today_weekday, lunar_date = get_current_time_info()
                    
                    # 构建带上下文的基础提示
                    context_prompt = f"""当前时间：{current_time}
                                        今天日期：{today_date} ({today_weekday})
                                        今天农历：{lunar_date}

                                        请根据以上信息回答用户的问题：{original_text}"""
                    
                    response = conn.intent.replyResult(context_prompt, original_text)
                    speak_txt(conn, response)
                
                conn.executor.submit(process_context_result)
                return True

            function_args = {}
            if "arguments" in intent_data["function_call"]:
                function_args = intent_data["function_call"]["arguments"]
                if function_args is None:
                    function_args = {}
            # 确保参数是字符串格式的JSON
            if isinstance(function_args, dict):
                function_args = json.dumps(function_args)

            function_call_data = {
                "name": function_name,
                "id": str(uuid.uuid4().hex),
                "arguments": function_args,
            }

            await send_stt_message(conn, original_text)
            conn.client_abort = False

            # 使用executor执行函数调用和结果处理
            def process_function_call():
                conn.dialogue.put(Message(role="user", content=original_text))
                setattr(conn, 'original_user_text', original_text)

                # 使用统一工具处理器处理所有工具调用
                try:
                    result = asyncio.run_coroutine_threadsafe(
                        conn.func_handler.handle_llm_function_call(
                            conn, function_call_data
                        ),
                        conn.loop,
                    ).result()
                except Exception as e:
                    conn.logger.bind(tag=TAG).error(f"工具调用失败: {e}")
                    result = ActionResponse(
                        action=Action.ERROR, result=str(e), response=str(e)
                    )

                if result:
                    if result.action == Action.RESPONSE:  # 直接回复前端
                        text = result.response
                        if text is not None:
                            speak_txt(conn, text)
                    elif result.action == Action.REQLLM:  # 调用函数后再请求llm生成回复
                        text = result.result
                        conn.dialogue.put(Message(role="tool", content=text))
                        llm_result = conn.intent.replyResult(text, original_text)
                        if llm_result is None:
                            llm_result = text
                        speak_txt(conn, llm_result)
                    elif (
                        result.action == Action.NOTFOUND
                        or result.action == Action.ERROR
                    ):
                        text = result.result
                        if text is not None:
                            speak_txt(conn, text)
                    elif function_name != "play_music":
                        # For backward compatibility with original code
                        # 获取当前最新的文本索引
                        text = result.response
                        if text is None:
                            text = result.result
                        if text is not None:
                            speak_txt(conn, text)

            # 将函数执行放在线程池中
            conn.executor.submit(process_function_call)
            return True
        return False
    except json.JSONDecodeError as e:
        conn.logger.bind(tag=TAG).error(f"处理意图结果时出错: {e}")
        return False


def speak_txt(conn, text):
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.FIRST,
            content_type=ContentType.ACTION,
        )
    )
    conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=text)
    conn.tts.tts_text_queue.put(
        TTSMessageDTO(
            sentence_id=conn.sentence_id,
            sentence_type=SentenceType.LAST,
            content_type=ContentType.ACTION,
        )
    )
    conn.dialogue.put(Message(role="assistant", content=text))
