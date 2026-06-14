import time
import json
import asyncio
from core.utils.util import audio_to_data
from core.handle.abortHandle import handleAbortMessage
from core.handle.intentHandler import handle_user_intent
from core.utils.output_counter import check_device_output_limit
from core.handle.sendAudioHandle import send_stt_message, SentenceType
from core.providers.tts.dto.dto import ContentType, TTSMessageDTO
from core.utils.dialogue import Dialogue, Message
import uuid

TAG = __name__


async def handleAudioMessage(conn, audio):
    # 更新最后音频输入时间，用于计算空闲间隔
    conn.last_audio_input_time = time.time()
    
    # 当前片段是否有人说话
    have_voice = conn.vad.is_vad(conn, audio)
    # 如果设备刚刚被唤醒，短暂忽略VAD检测
    if have_voice and hasattr(conn, "just_woken_up") and conn.just_woken_up:
        have_voice = False
        # 设置一个短暂延迟后恢复VAD检测
        conn.asr_audio.clear()
        if not hasattr(conn, "vad_resume_task") or conn.vad_resume_task.done():
            conn.vad_resume_task = asyncio.create_task(resume_vad_detection(conn))
        return
    if have_voice:
        # [Modified] 只要用户开始说话，强制打断一切：
        # 1. 如果TTS正在播报 (client_is_speaking)
        # 2. 如果后台工具正在运行 (_tool_running)
        # 3. 如果视觉任务由于延时等原因还在"飞行"中 (_vision_inflight)
        # 这样确保用户的新指令拥有最高优先级，清理所有旧状态。
        # [User Request] 移除强制打断功能，避免环境噪音误触导致任务取消
        # if conn.client_is_speaking or getattr(conn, "_tool_running", False) or getattr(conn, "_vision_inflight", False):
        #    conn.logger.bind(tag=TAG).info(f"收到打断请求: 检测到新语音，强制终止当前任务 (TTS:{conn.client_is_speaking}, Tool:{getattr(conn, '_tool_running', False)}, Vision:{getattr(conn, '_vision_inflight', False)})")
        #    await handleAbortMessage(conn)
        pass 
    # 设备长时间空闲检测，用于say goodbye
    await no_voice_close_connect(conn, have_voice)
    # 接收音频
    await conn.asr.receive_audio(conn, audio, have_voice)


async def resume_vad_detection(conn):
    # 等待2秒后恢复VAD检测
    await asyncio.sleep(1)
    conn.just_woken_up = False


async def startToChat(conn, text):
    # 检查输入是否是JSON格式（包含说话人信息）
    speaker_name = None
    actual_text = text

    # ------------------------------------------------------------------
    # 【新增】检测会话空闲超时（5秒），若超时则通过 handleAbortMessage 
    # 清理所有在此期间可能残留的资源（如TTS、队列），并重置上下文历史
    # ------------------------------------------------------------------
    if hasattr(conn, "last_activity_time") and conn.last_activity_time > 0:
        # last_activity_time 是毫秒，转换为秒
        last_server_time = conn.last_activity_time / 1000.0
        # 获取最后音频输入时间（若无则取当前时间）
        last_audio_time = getattr(conn, "last_audio_input_time", time.time())
        
        # 估算说话时长（保守估计：每字符0.2秒）
        # 目的：计算出用户“开始说话”前，系统实际空闲了多久
        est_speech_duration = len(text) * 0.2
        
        # 空闲时间 = (音频结束时刻 - 上次服务结束时刻) - 估算的说话时长
        idle_time = (last_audio_time - last_server_time) - est_speech_duration
        
        if idle_time > 5.0: # 5秒超时
            conn.logger.bind(tag=TAG).info(f"检测到会话空闲约 {idle_time:.1f}s (>5s)，执行资源释放与上下文重置")
            
            # 1. 强制清理之前的任务/语音/队列资源
            # 注意：这会发送 stopped 状态给设备，且设置 client_abort=True
            await handleAbortMessage(conn)
            
            # 2. 关键：将 client_abort 重置为 False，否则本次新对话也会被拦截
            conn.client_abort = False
            
            # 3. 重置对话历史（上下文），消除幻觉
            try:
                conn.dialogue = Dialogue()
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"重置Dialogue失败: {e}")

            # 3.5 对话练习激活时，重新注入英语教师prompt和对话内容
            if getattr(conn, "dialogue_practice", {}).get("active"):
                try:
                    practice = conn.dialogue_practice
                    conn.dialogue.update_system_message(practice["system_prompt"])
                    conn.prompt = practice["system_prompt"]
                    if practice.get("content"):
                        conn.dialogue.put(Message(
                            role="assistant",
                            content=f"[模式恢复：严格的英语课本对话练习]\n之前识别的对话剧本来原：\n{practice['content']}\n"
                                    f"请继续严格按照图片提取的剧本陪用户进行口语练习。核对用户发音，准确就表扬并对下一句台词，不准确就纠正并重试。勿闲聊自由发挥！"
                        ))
                    conn.logger.bind(tag=TAG).info(f"对话练习会话已恢复 (内容长度: {len(practice.get('content', ''))})")
                except Exception as e:
                    conn.logger.bind(tag=TAG).error(f"恢复对话练习会话失败: {e}")
                
            # 4. 再次确保兜底文本被清除
            if hasattr(conn, "tts_MessageText"):
                conn.tts_MessageText = None
    # ------------------------------------------------------------------

    try:
        # 尝试解析JSON格式的输入
        if text.strip().startswith("{") and text.strip().endswith("}"):
            data = json.loads(text)
            if "speaker" in data and "content" in data:
                speaker_name = data["speaker"]
                actual_text = data["content"]
                conn.logger.bind(tag=TAG).info(f"解析到说话人信息: {speaker_name}")

                # 直接使用JSON格式的文本，不解析
                actual_text = text
    except (json.JSONDecodeError, KeyError):
        # 如果解析失败，继续使用原始文本
        pass

    # 保存说话人信息到连接对象
    if speaker_name:
        conn.current_speaker = speaker_name
    else:
        conn.current_speaker = None

    # 重置TTS状态以开启新一轮对话
    if hasattr(conn, "tts"):
        # 重置首句标记，确保下发 'start' 指令令设备重置解码器缓冲区
        conn.tts.tts_audio_first_sentence = True
    
    # 重置音频流控状态，防止因上一轮时间戳导致的音频数据突发发送(Burst)造成丢包
    if hasattr(conn, "audio_flow_control"):
        delattr(conn, "audio_flow_control")
        
    # 重置会话ID，确保TTS服务开启新任务
    if hasattr(conn, "sentence_id"):
        conn.sentence_id = None

    # 重置兜底文本，防止上一轮残留的文本在TTS失败时被错误播报
    if hasattr(conn, "tts_MessageText"):
        conn.tts_MessageText = None
        
    # 检测是否有“不要语音”的指令
    if "不要语音" in actual_text:
        conn.silent_mode_once = True
        conn.logger.bind(tag=TAG).info("检测到“不要语音”指令，本轮对话将只显示文本")
        # 从用户输入中移除指令部分，仅将剩余内容发送给大模型
        actual_text = actual_text.replace("不要语音", "").replace("，", "").replace(",", "").strip()
        # 如果去除指令后为空，则不继续对话，但也标志着指令生效
        if not actual_text:
             conn.logger.bind(tag=TAG).info("用户仅发送了指令，无需回复")
             return
    else:
        conn.silent_mode_once = False

    if conn.need_bind:
        await check_bind_device(conn)
        return

    # 敏感词过滤
    filter_keywords = ["美女", "帅哥", "脏话", "笨蛋", "傻瓜", "卧槽", "TMD", "NMD", "SB", "傻逼"]
    for kw in filter_keywords:
        if kw in actual_text:
            conn.logger.bind(tag=TAG).info(f"检测到敏感词: {kw}，拒绝回答")
            await send_stt_message(conn, actual_text)
            
            conn.sentence_id = str(uuid.uuid4().hex)
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.FIRST, content_type=ContentType.ACTION)
            )
            conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail="我希望你提出更有价值的问题！")
            conn.tts.tts_text_queue.put(
                TTSMessageDTO(sentence_id=conn.sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION)
            )
            return

    # 如果当日的输出字数大于限定的字数
    if conn.max_output_size > 0:
        if check_device_output_limit(
            conn.headers.get("device-id"), conn.max_output_size
        ):
            await max_out_size(conn)
            return
    if conn.client_is_speaking:
        await handleAbortMessage(conn)

    # 首先进行意图分析，使用实际文本内容
    intent_handled = await handle_user_intent(conn, actual_text)

    if intent_handled:
        # 如果意图已被处理，不再进行聊天
        return

    eval_text = actual_text
    if getattr(conn, "dialogue_practice", {}).get("active") and conn.dialogue_practice.get("content"):
        eval_text = (
            f"{actual_text}\n\n"
            f"【系统强制指令】：当前正处于英语课本对话练习模式。请仔细核对上方用户的发音文本与剧本台词是否一致。\n"
            f"1. 发音准确：用简短的中文表扬鼓励用户，然后立即念出【接下来的剧本内容中属于你的台词】。\n"
            f"2. 发音不够准确：用中文温和地指出错误，并要求用户再读一遍。\n"
            f"禁止任何偏离剧本的自由发挥或闲聊，绝不自己瞎编回复，必须严格遵守提取到的剧本原文进行对话！"
        )

    # 意图未被处理，继续常规聊天流程，使用实际文本内容
    await send_stt_message(conn, actual_text)
    conn.executor.submit(conn.chat, eval_text)


async def no_voice_close_connect(conn, have_voice):
    if have_voice:
        conn.last_activity_time = time.time() * 1000
        return
    # 只有在已经初始化过时间戳的情况下才进行超时检查
    if conn.last_activity_time > 0.0:
        no_voice_time = time.time() * 1000 - conn.last_activity_time
        close_connection_no_voice_time = int(
            conn.config.get("close_connection_no_voice_time", 120)
        )
        if (
            not conn.close_after_chat
            and no_voice_time > 1000 * close_connection_no_voice_time
        ):
            conn.close_after_chat = True
            conn.client_abort = False
            end_prompt = conn.config.get("end_prompt", {})
            if end_prompt and end_prompt.get("enable", True) is False:
                conn.logger.bind(tag=TAG).info("结束对话，无需发送结束提示语")
                await conn.close()
                return
            prompt = end_prompt.get("prompt")
            if not prompt:
                prompt = "请你以```时间过得真快```未来头，用富有感情、依依不舍的话来结束这场对话吧。！"
            await startToChat(conn, prompt)


async def max_out_size(conn):
    # 播放超出最大输出字数的提示
    conn.client_abort = False
    text = "不好意思，我现在有点事情要忙，明天这个时候我们再聊，约好了哦！明天不见不散，拜拜！"
    await send_stt_message(conn, text)
    file_path = "config/assets/max_output_size.wav"
    opus_packets = audio_to_data(file_path)
    conn.tts.tts_audio_queue.put((SentenceType.LAST, opus_packets, text))
    conn.close_after_chat = True


async def check_bind_device(conn):
    if conn.bind_code:
        # 确保bind_code是6位数字
        if len(conn.bind_code) != 6:
            conn.logger.bind(tag=TAG).error(f"无效的绑定码格式: {conn.bind_code}")
            text = "绑定码格式错误，请检查配置。"
            await send_stt_message(conn, text)
            return

        text = f"请登录控制面板，输入{conn.bind_code}，绑定设备。"
        await send_stt_message(conn, text)

        # 播放提示音
        music_path = "config/assets/bind_code.wav"
        opus_packets = audio_to_data(music_path)
        conn.tts.tts_audio_queue.put((SentenceType.FIRST, opus_packets, text))

        # 逐个播放数字
        for i in range(6):  # 确保只播放6位数字
            try:
                digit = conn.bind_code[i]
                num_path = f"config/assets/bind_code/{digit}.wav"
                num_packets = audio_to_data(num_path)
                conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, num_packets, None))
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"播放数字音频失败: {e}")
                continue
        conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))
    else:
        # 播放未绑定提示
        conn.client_abort = False
        text = f"没有找到该设备的版本信息，请正确配置 OTA地址，然后重新编译固件。"
        await send_stt_message(conn, text)
        music_path = "config/assets/bind_not_found.wav"
        opus_packets = audio_to_data(music_path)
        conn.tts.tts_audio_queue.put((SentenceType.LAST, opus_packets, text))
