"""连接注册表：用于在HTTP视觉处理完成后，直接找到对应的WebSocket连接进行桥接播报。

简单的进程内全局注册，按 device-id 与 client-id 建立索引。
"""
from typing import Optional, List
from threading import RLock


_by_device = {}
_by_client = {}
_lock = RLock()


def register(conn) -> None:
    did = getattr(conn, "device_id", None)
    cid = None
    try:
        if getattr(conn, "headers", None):
            cid = conn.headers.get("client-id")
    except Exception:
        cid = None
    with _lock:
        if did:
            _by_device.setdefault(did, set()).add(conn)
        if cid:
            _by_client.setdefault(cid, set()).add(conn)


def unregister(conn) -> None:
    with _lock:
        # 从 device 索引移除
        try:
            did = getattr(conn, "device_id", None)
            if did and did in _by_device and conn in _by_device[did]:
                _by_device[did].discard(conn)
                if not _by_device[did]:
                    _by_device.pop(did, None)
        except Exception:
            pass
        # 从 client 索引移除
        try:
            cid = None
            if getattr(conn, "headers", None):
                cid = conn.headers.get("client-id")
            if cid and cid in _by_client and conn in _by_client[cid]:
                _by_client[cid].discard(conn)
                if not _by_client[cid]:
                    _by_client.pop(cid, None)
        except Exception:
            pass


def find(device_id: Optional[str] = None, client_id: Optional[str] = None) -> List:
    """按 device_id 与/或 client_id 查找连接。优先 client_id 精确匹配，其次 device_id。"""
    with _lock:
        if client_id and client_id in _by_client:
            return [c for c in list(_by_client[client_id])]
        if device_id and device_id in _by_device:
            return [c for c in list(_by_device[device_id])]
    return []
