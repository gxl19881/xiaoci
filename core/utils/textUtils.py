import json
import re

TAG = __name__
EMOJI_MAP = {
    "😂": "laughing",
    "😭": "crying",
    "😠": "angry",
    "😔": "sad",
    "😍": "loving",
    "😲": "surprised",
    "😱": "shocked",
    "🤔": "thinking",
    "😌": "relaxed",
    "😴": "sleepy",
    "😜": "silly",
    "🙄": "confused",
    "😶": "neutral",
    "🙂": "happy",
    "😆": "laughing",
    "😳": "embarrassed",
    "😉": "winking",
    "😎": "cool",
    "🤤": "delicious",
    "😘": "kissy",
    "😏": "confident",
}
EMOJI_RANGES = [
    (0x1F600, 0x1F64F),
    (0x1F300, 0x1F5FF),
    (0x1F680, 0x1F6FF),
    (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
]


def get_string_no_punctuation_or_emoji(s):
    """去除字符串首尾的空格、标点符号和表情符号"""
    chars = list(s)
    # 处理开头的字符
    start = 0
    while start < len(chars) and is_punctuation_or_emoji(chars[start]):
        start += 1
    # 处理结尾的字符
    end = len(chars) - 1
    while end >= start and is_punctuation_or_emoji(chars[end]):
        end -= 1
    return "".join(chars[start : end + 1])


def is_punctuation_or_emoji(char):
    """检查字符是否为空格、指定标点或表情符号"""
    # 定义需要去除的中英文标点（包括全角/半角）
    punctuation_set = {
        "，",
        ",",  # 中文逗号 + 英文逗号
        "。",
        ".",  # 中文句号 + 英文句号
        "！",
        "!",  # 中文感叹号 + 英文感叹号
        "“",
        "”",
        '"',  # 中文双引号 + 英文引号
        "：",
        ":",  # 中文冒号 + 英文冒号
        "-",
        "－",  # 英文连字符 + 中文全角横线
        "、",  # 中文顿号
        "[",
        "]",  # 方括号
        "【",
        "】",  # 中文方括号
    }
    if char.isspace() or char in punctuation_set:
        return True
    return is_emoji(char)


async def get_emotion(conn, text):
    """获取文本内的情绪消息"""
    emoji = "🙂"
    emotion = "happy"
    for char in text:
        if char in EMOJI_MAP:
            emoji = char
            emotion = EMOJI_MAP[char]
            break
    try:
        await conn.websocket.send(
            json.dumps(
                {
                    "type": "llm",
                    "text": emoji,
                    "emotion": emotion,
                    "session_id": conn.session_id,
                }
            )
        )
    except Exception as e:
        conn.logger.bind(tag=TAG).warning(f"发送情绪表情失败，错误:{e}")
    return


def is_emoji(char):
    """检查字符是否为emoji表情"""
    code_point = ord(char)
    return any(start <= code_point <= end for start, end in EMOJI_RANGES)


def check_emoji(text):
    """去除文本中的所有emoji表情"""
    return ''.join(char for char in text if not is_emoji(char) and char != "\n")


def sanitize_for_device(text: str) -> str:
    """
    发送到设备前的文本清洗：
    - 去掉 Markdown 标题符号(#、##、###等行首标记)
    - 去掉粗体/斜体标记(**、__、*) 与行内代码反引号(`)
    - 去掉 LaTeX 定界符 (\( \)、$$ $$、$)
    - 将乘号/错误标记 × 替换为“错”（避免在屏显/播报中出现奇怪符号）
    - 移除多余反斜杠
    - 规范空白：去掉每行行尾双空格、合并多空格，保留换行
    """
    if not text:
        return text

    s = text
    # 1) 去除行首的 Markdown 标题#
    lines = s.splitlines()
    cleaned_lines = []
    heading_re = re.compile(r"^\s{0,3}#{1,6}\s*")
    for ln in lines:
        ln = heading_re.sub("", ln)
        cleaned_lines.append(ln)
    s = "\n".join(cleaned_lines)

    # 2) 去掉粗体/斜体与反引号
    s = s.replace("**", "").replace("__", "")
    s = s.replace("`", "")
    # 谨慎处理单星号：仅删除成对包裹的样式用法
    s = re.sub(r"\*(\S.*?)\*", r"\1", s)

    # 3) 去除 LaTeX 定界符
    s = s.replace("\\(", "(").replace("\\)", ")")
    # 去掉 $$ 块与 $ 行内定界符（仅移除定界符，不改动中间内容）
    s = s.replace("$$", "")
    s = s.replace("$", "")

    # 3.5) 替换常见 LaTeX 数学符号
    s = s.replace("\\div", "÷")
    s = s.replace("\\times", "×")
    s = re.sub(r"\\boldsymbol\s*\{(.*?)\}", r"\1", s)
    s = re.sub(r"\\mathbf\s*\{(.*?)\}", r"\1", s)
    s = re.sub(r"\\text\s*\{(.*?)\}", r"\1", s)

    # 4) 特殊符号规范
    # s = s.replace("×", "错")  # 移除此行，避免误伤乘号
    # 可能出现的多余反斜杠
    s = s.replace("\\", "")

    # 5) 去除行尾双空格（Markdown换行）并规范空白
    lines = [re.sub(r"\s+$", "", ln) for ln in s.splitlines()]
    s = "\n".join(lines)
    # 合并连续超过2个空格为单空格（不破坏换行）
    s = re.sub(r"[ \t]{2,}", " ", s)

    # 再次调用严格的Emoji去除
    s = check_emoji(s)

    return s


def keep_cn_en_punct(text: str) -> str:
    """
    仅保留常用中文/英文字符与常用标点，强力去噪：
    - 删除看起来像 JSON 的片段（{}、[] 包裹内容）
    - 严格白名单：
      * 中文汉字范围：\u4e00-\u9fff
      * 常见中文标点：\u3001、\u3002、\uff0c、\uff01、\uff1f、\uff1b、\uff1a、\uff08、\uff09、\u300a、\u300b、\u2014、\u2018-\u2019、\u201c-\u201d、\u2026
      * 英文/数字：a-z A-Z 0-9
      * 空白：空格与换行
      * 少量ASCII标点：.,!?;()'-/+
    - 显式剔除易引入结构噪声的符号：{}[]<>:@#&=\`~^|
    """
    if not text:
        return text

    s = str(text)
    # 先粗暴移除一层 JSON/数组片段
    # 注意：为避免卡死，仅做非贪婪、单层匹配，多次应用2次
    for _ in range(2):
        s = re.sub(r"\{[^{}]*\}", "", s)
        s = re.sub(r"\[[^\[\]]*\]", "", s)

    # 逐字符过滤（白名单）
    allowed_ascii = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,!?:;()'\- /+\n")
    # 需要排除的ASCII符号（即便上面在allowed也会强制剔除）
    exclude_ascii = set("{}[]<>:@#&=\\`~^|")

    def _keep(ch: str) -> bool:
        if ch in exclude_ascii:
            return False
        code = ord(ch)
        # 中文汉字
        if 0x4E00 <= code <= 0x9FFF:
            return True
        # Latin-1 Supplement & Latin Extended-A/B (covers Pinyin tones)
        if 0x0080 <= code <= 0x024F:
            return True
        # 常见中文标点和CJK符号
        if ch in ("、", "。", "，", "！", "？", "；", "：", "（", "）", "《", "》", "—", "…", "“", "”", "‘", "’"):
            return True
        # 空白
        if ch == " " or ch == "\n":
            return True
        # 允许的ASCII集合
        if ch in allowed_ascii:
            return True
        return False

    s = "".join(ch for ch in s if _keep(ch))

    # 规范多余空白：合并超过2个空格为一个，清理多余换行
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # 去掉行首尾空白
    s = "\n".join(ln.strip() for ln in s.splitlines())
    return s
