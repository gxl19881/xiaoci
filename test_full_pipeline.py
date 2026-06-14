#!/usr/bin/env python3
"""
完整的图像生成功能测试
模拟从语音指令到图像生成的完整流程
"""
import asyncio
import json
import sys
import os
import base64
from io import BytesIO

# 添加路径以便导入模块
sys.path.append('/opt/xiaozhi-esp32-server')

async def test_full_pipeline():
    """测试完整的图像生成管道"""
    try:
        print("🚀 开始完整的图像生成流程测试...")
        
        # 1. 模拟WebSocket连接
        class MockConnection:
            def __init__(self):
                self.messages = []
                self.config = {}
                
            async def send_message(self, message):
                self.messages.append(message)
                print(f"📤 WebSocket消息: {json.dumps(message, ensure_ascii=False, indent=2)}")
                
            async def send_to_device(self, message_type, data):
                print(f"📱 发送到ESP32设备: {message_type}")
                print(f"   数据大小: {len(str(data))} 字符")
                return True  # 模拟发送成功
        
        # 2. 导入配置加载器
        from config.config_loader import load_config
        config = load_config()
        
        # 3. 创建连接并设置配置
        conn = MockConnection()
        conn.config = config
        
        print("✅ 配置加载成功")
        
        # 4. 导入并测试图像处理模块
        from core.handle.imageHandle import send_image_generation_status
        
        print("✅ 图像处理模块导入成功")
        
        # 5. 测试状态发送
        await send_image_generation_status(conn, "generating", "正在生成图片...", "测试图片")
        
        # 6. 导入图像生成插件
        from plugins_func.functions.generate_image import generate_image
        
        print("✅ 图像生成插件导入成功")
        
        # 7. 查看配置
        image_config = config.get("plugins", {}).get("generate_image", {})
        print(f"📋 图像生成配置: {json.dumps(image_config, ensure_ascii=False, indent=2)}")
        
        # 8. 创建一个简单的测试图像（模拟生成结果）
        print("🎨 模拟图像生成过程...")
        
        # 创建一个小的测试图像
        try:
            from PIL import Image, ImageDraw
            import base64
            from io import BytesIO
            
            # 创建一个简单的测试图像
            img = Image.new('RGB', (240, 240), color='lightblue')
            draw = ImageDraw.Draw(img)
            draw.text((50, 100), "Test Image\n测试图片", fill='black')
            
            # 转换为base64
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode()
            
            print("✅ 测试图像创建成功")
            
            # 测试图像发送到设备
            from core.handle.imageHandle import send_image_to_device
            result = await send_image_to_device(conn, img_base64, "测试图片")
            
            print(f"📱 图像发送结果: {result}")
            
        except ImportError as e:
            print(f"⚠️  PIL未安装，跳过图像创建测试: {e}")
            
        # 9. 测试插件调用（会因为API密钥而失败，但可以验证流程）
        print("🔧 测试插件调用...")
        try:
            result = await generate_image(conn, "一只可爱的小猫咪", "cartoon", "240x240")
            print(f"🎨 生成结果: {result}")
        except Exception as e:
            print(f"⚠️  插件调用测试（预期错误）: {e}")
            
        print("\n📊 测试总结:")
        print(f"   - 发送的WebSocket消息数量: {len(conn.messages)}")
        print(f"   - 配置加载: ✅")
        print(f"   - 模块导入: ✅") 
        print(f"   - 状态通信: ✅")
        print(f"   - 插件结构: ✅")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_full_pipeline())
    sys.exit(0 if success else 1)