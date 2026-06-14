from typing import Dict, Any
from config.logger import setup_logging
from core.utils import tts, llm, intent, memory, vad, asr

TAG = __name__
logger = setup_logging()


def initialize_modules(
    logger,
    config: Dict[str, Any],
    init_vad=False,
    init_asr=False,
    init_llm=False,
    init_tts=False,
    init_memory=False,
    init_intent=False,
) -> Dict[str, Any]:
    """
    初始化所有模块组件

    Args:
        config: 配置字典

    Returns:
        Dict[str, Any]: 包含所有初始化后的模块的字典
    """
    modules = {}

    # 初始化TTS模块
    if init_tts:
        select_tts_module = config["selected_module"]["TTS"]
        modules["tts"] = initialize_tts(config)
        logger.bind(tag=TAG).info(f"初始化组件: tts成功 {select_tts_module}")

    # 初始化LLM模块
    if init_llm:
        select_llm_module = config["selected_module"]["LLM"]
        provider_cfg = config.get("LLM", {}).get(select_llm_module)
        if not provider_cfg:
            logger.bind(tag=TAG).error(
                f"初始化组件: llm失败，未找到配置 LLM.{select_llm_module} 或配置为空"
            )
        else:
            llm_type = (
                select_llm_module
                if "type" not in provider_cfg
                else provider_cfg["type"]
            )
            modules["llm"] = llm.create_instance(
                llm_type,
                provider_cfg,
            )
            logger.bind(tag=TAG).info(f"初始化组件: llm成功 {select_llm_module}")

    # 初始化Intent模块
    if init_intent:
        select_intent_module = config["selected_module"]["Intent"]
        provider_cfg = config.get("Intent", {}).get(select_intent_module)
        if not provider_cfg:
            logger.bind(tag=TAG).error(
                f"初始化组件: intent失败，未找到配置 Intent.{select_intent_module} 或配置为空"
            )
        else:
            intent_type = (
                select_intent_module
                if "type" not in provider_cfg
                else provider_cfg["type"]
            )
            modules["intent"] = intent.create_instance(
                intent_type,
                provider_cfg,
            )
            logger.bind(tag=TAG).info(f"初始化组件: intent成功 {select_intent_module}")

    # 初始化Memory模块
    if init_memory:
        select_memory_module = config["selected_module"]["Memory"]
        provider_cfg = config.get("Memory", {}).get(select_memory_module)
        if not provider_cfg:
            logger.bind(tag=TAG).error(
                f"初始化组件: memory失败，未找到配置 Memory.{select_memory_module} 或配置为空"
            )
        else:
            memory_type = (
                select_memory_module
                if "type" not in provider_cfg
                else provider_cfg["type"]
            )
            modules["memory"] = memory.create_instance(
                memory_type,
                provider_cfg,
                config.get("summaryMemory", None),
            )
            logger.bind(tag=TAG).info(f"初始化组件: memory成功 {select_memory_module}")

    # 初始化VAD模块
    if init_vad:
        select_vad_module = config["selected_module"]["VAD"]
        provider_cfg = config.get("VAD", {}).get(select_vad_module)
        if not provider_cfg:
            logger.bind(tag=TAG).error(
                f"初始化组件: vad失败，未找到配置 VAD.{select_vad_module} 或配置为空"
            )
        else:
            vad_type = (
                select_vad_module
                if "type" not in provider_cfg
                else provider_cfg["type"]
            )
            modules["vad"] = vad.create_instance(
                vad_type,
                provider_cfg,
            )
            logger.bind(tag=TAG).info(f"初始化组件: vad成功 {select_vad_module}")

    # 初始化ASR模块
    if init_asr:
        select_asr_module = config["selected_module"]["ASR"]
        try:
            modules["asr"] = initialize_asr(config)
            logger.bind(tag=TAG).info(f"初始化组件: asr成功 {select_asr_module}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"初始化组件: asr失败 {select_asr_module}: {e}")
    return modules


def initialize_tts(config):
    select_tts_module = config["selected_module"]["TTS"]
    tts_type = (
        select_tts_module
        if "type" not in config["TTS"][select_tts_module]
        else config["TTS"][select_tts_module]["type"]
    )
    new_tts = tts.create_instance(
        tts_type,
        config["TTS"][select_tts_module],
        str(config.get("delete_audio", True)).lower() in ("true", "1", "yes"),
    )
    return new_tts


def initialize_asr(config):
    select_asr_module = config["selected_module"]["ASR"]
    asr_type = (
        select_asr_module
        if "type" not in config["ASR"][select_asr_module]
        else config["ASR"][select_asr_module]["type"]
    )
    new_asr = asr.create_instance(
        asr_type,
        config["ASR"][select_asr_module],
        str(config.get("delete_audio", True)).lower() in ("true", "1", "yes"),
    )
    logger.bind(tag=TAG).info("ASR模块初始化完成")
    return new_asr


def initialize_voiceprint(asr_instance, config):
    """初始化声纹识别功能"""
    voiceprint_config = config.get("voiceprint")
    if not voiceprint_config:
        return False  

    # 应用配置
    if not voiceprint_config.get("url") or not voiceprint_config.get("speakers"):
        logger.bind(tag=TAG).warning("声纹识别配置不完整")
        return False
        
    try:
        asr_instance.init_voiceprint(voiceprint_config)
        logger.bind(tag=TAG).info("ASR模块声纹识别功能已动态启用")
        logger.bind(tag=TAG).info(f"配置说话人数量: {len(voiceprint_config['speakers'])}")
        return True
    except Exception as e:
        logger.bind(tag=TAG).error(f"动态初始化声纹识别功能失败: {str(e)}")
        return False

