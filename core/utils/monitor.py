import time
import threading
from collections import deque
from typing import Deque, Dict, Any


class _ConnectionMonitor:
    """
    轻量连接监控：记录当前活跃连接数、累计连接次数、最近连接/断开事件。
    线程安全（用于 asyncio 与其他线程环境）。
    """

    def __init__(self, max_events: int = 200):
        self._lock = threading.Lock()
        self.active_count = 0
        self.total_accepted = 0
        self.total_closed = 0
        self.recent_events: Deque[Dict[str, Any]] = deque(maxlen=max_events)

    def on_connected(self, remote: str | None = None):
        ts = time.time()
        with self._lock:
            self.active_count += 1
            self.total_accepted += 1
            self.recent_events.appendleft(
                {"type": "connected", "remote": remote, "ts": ts}
            )

    def on_closed(self, remote: str | None = None, reason: str | None = None):
        ts = time.time()
        with self._lock:
            self.active_count = max(0, self.active_count - 1)
            self.total_closed += 1
            self.recent_events.appendleft(
                {"type": "closed", "remote": remote, "reason": reason, "ts": ts}
            )

    def snapshot(self, limit: int = 50) -> Dict[str, Any]:
        with self._lock:
            events = list(self.recent_events)[:limit]
            return {
                "active": self.active_count,
                "total_accepted": self.total_accepted,
                "total_closed": self.total_closed,
                "recent_events": events,
                "server_time": time.time(),
            }


# 全局单例
monitor = _ConnectionMonitor()
