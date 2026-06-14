#!/usr/bin/env python3
"""
测试图像生成插件功能
"""
import asyncio
import json
import sys
import os

# 添加路径以便导入模块
sys.path.append('/opt/xiaozhi-esp32-server')

async def test_generate_image():
    """测试图像生成功能"""
    try:
        # 导入插件
        from plugins_func.functions.generate_image import generate_image
        
        print("✅ generate_image插件导入成功")
        
        # 模拟连接对象
        class MockConnection:
            def __init__(self):
                self.messages = []
                
            async def send_message(self, message):
                self.messages.append(message)
                print(f"📤 发送消息: {json.dumps(message, ensure_ascii=False)}")
        
        # 创建模拟连接
        conn = MockConnection()
        
        # 测试生成图像（会因为没有API密钥而失败，但能验证插件结构）
        print("🎨 开始测试图像生成...")
        result = await generate_image(conn, "一只可爱的小猫", "cartoon", "512x512")
        
        print(f"📋 生成结果: {result}")
        print(f"📨 发送的消息数量: {len(conn.messages)}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_generate_image())
    sys.exit(0 if success else 1)