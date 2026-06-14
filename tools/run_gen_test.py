import asyncio
import json

from config.config_loader import load_config
from plugins_func.functions.generate_image import generate_image

class MockWS:
    async def send(self, msg):
        # Print only the first 200 chars to keep output short
        try:
            s = msg if isinstance(msg, str) else msg.decode()
        except Exception:
            s = str(msg)
        print("[WS]->", s[:200])

class Conn:
    def __init__(self, cfg):
        self.config = cfg
        self.websocket = MockWS()

async def main():
    cfg = load_config()
    conn = Conn(cfg)
    res = await generate_image(conn, "一只可爱的小猫在窗台上，阳光洒在它的毛发上", "cartoon", "240x240")
    print("Action:", res.action.name, "Result:", res.result)

if __name__ == "__main__":
    asyncio.run(main())
