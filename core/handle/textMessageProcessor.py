import json
from core.utils.student_id_store import add_sid

from core.handle.textMessageHandlerRegistry import TextMessageHandlerRegistry

TAG = __name__


class TextMessageProcessor:
    """消息处理器主类"""

    def __init__(self, registry: TextMessageHandlerRegistry):
        self.registry = registry

    async def process_message(self, conn, message: str) -> None:
        """处理消息的主入口"""
        try:
            # 解析JSON消息
            msg_json = json.loads(message)

            # 处理JSON消息
            if isinstance(msg_json, dict):
                message_type = msg_json.get("type")

                # 仅在可信的消息类型中允许更新 student_id，防止非预期消息覆盖绑定
                try:
                    sid = str(msg_json.get("student_id", "")).strip()
                    header_sid = str(msg_json.get("Student-Id", "")).strip()
                    candidate_sid = sid or header_sid

                    # 仅接受纯数字的学号
                    def is_valid_sid(s: str) -> bool:
                        return s.isdigit() and 1 <= len(s) <= 32

                    allow_update = False
                    if message_type == "hello":
                        allow_update = True
                    elif message_type == "listen" and msg_json.get("state") == "stop":
                        # 仅在一次说话结束时允许以消息体显式提交的学号更新绑定
                        allow_update = True
                    elif message_type == "update_student_id":
                        allow_update = True

                    if allow_update and candidate_sid and is_valid_sid(candidate_sid):
                        prev = getattr(conn, "student_id", None)
                        if prev != candidate_sid:
                            conn.student_id = candidate_sid
                            conn.logger.bind(tag=TAG).info(
                                f"更新连接学号({message_type}) {prev} -> {conn.student_id}"
                            )
                            try:
                                add_sid(conn.student_id)
                            except Exception:
                                pass
                except Exception as _e:
                    conn.logger.bind(tag=TAG).warning(f"解析/更新学号异常: {_e}")

                # 记录日志
                conn.logger.bind(tag=TAG).info(f"收到{message_type}消息：{message}")

                # 获取并执行处理器
                handler = self.registry.get_handler(message_type)
                if handler:
                    await handler.handle(conn, msg_json)
                else:
                    conn.logger.bind(tag=TAG).error(f"收到未知类型消息：{message}")
            # 处理纯数字消息
            elif isinstance(msg_json, int):
                conn.logger.bind(tag=TAG).info(f"收到数字消息：{message}")
                await conn.websocket.send(message)

        except json.JSONDecodeError:
            # 非JSON消息直接转发
            conn.logger.bind(tag=TAG).error(f"解析到错误的消息：{message}")
            await conn.websocket.send(message)
