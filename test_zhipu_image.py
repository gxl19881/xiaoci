#!/usr/bin/env python3
"""
直接测试智谱AI图像生成功能
"""
import asyncio
import json
import sys
import os

# 添加路径以便导入模块
sys.path.append('/opt/xiaozhi-esp32-server')

async def test_zhipu_image_generation():
    """测试智谱AI图像生成"""
    try:
        print("🚀 开始测试智谱AI图像生成...")
        
        # 导入配置加载器
        from config.config_loader import load_config
        config = load_config()
        
        # 检查配置
        image_config = config.get("plugins", {}).get("generate_image", {})
        provider = image_config.get("provider", "")
        api_key = image_config.get("zhipu_api_key", "")
        
        print(f"📋 当前配置:")
        print(f"   提供商: {provider}")
        print(f"   API密钥: {api_key[:20]}..." if api_key else "   API密钥: 未配置")
        
        if provider != "zhipu":
            print("⚠️  提供商不是智谱AI，但继续测试...")
            
        if not api_key or api_key == "your-zhipu-api-key":
            print("❌ 智谱AI API密钥未正确配置")
            return False
            
        # 导入生成函数
        from plugins_func.functions.generate_image import generate_image_zhipu
        
        print("✅ 图像生成函数导入成功")
        
        # 测试生成
        test_prompt = "一只可爱的小猫咪，卡通风格"
        print(f"🎨 开始生成图片: {test_prompt}")
        
        image_base64 = generate_image_zhipu(
            prompt=test_prompt,
            api_key=api_key,
            style="cartoon",
            size="240x240"
        )
        
        if image_base64:
            print("✅ 图片生成成功!")
            print(f"📸 图片数据长度: {len(image_base64)} 字符")
            print(f"🎯 图片格式: base64编码")
            
            # 保存图片到文件进行验证
            import base64
            try:
                image_data = base64.b64decode(image_base64)
                with open('/opt/xiaozhi-esp32-server/test_generated_image.jpg', 'wb') as f:
                    f.write(image_data)
                print("💾 图片已保存到: /opt/xiaozhi-esp32-server/test_generated_image.jpg")
            except Exception as e:
                print(f"⚠️  保存图片失败: {e}")
            
            return True
        else:
            print("❌ 图片生成失败")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_full_pipeline_with_zhipu():
    """测试完整的图像生成管道"""
    try:
        print("\n🔄 测试完整的图像生成管道...")
        
        # 模拟连接对象
        class MockConnection:
            def __init__(self, config):
                self.messages = []
                self.config = config
                
            async def send_message(self, message):
                self.messages.append(message)
                print(f"📤 WebSocket消息: {json.dumps(message, ensure_ascii=False)}")
        
        # 加载配置并创建连接
        from config.config_loader import load_config
        config = load_config()
        conn = MockConnection(config)
        
        # 导入主生成函数
        from plugins_func.functions.generate_image import generate_image
        
        print("🎨 调用主生成函数...")
        result = await generate_image(conn, "一只可爱的小猫咪", "cartoon", "240x240")
        
        print(f"📋 生成结果类型: {type(result)}")
        print(f"📨 发送的消息数量: {len(conn.messages)}")
        
        for i, msg in enumerate(conn.messages):
            print(f"  消息 {i+1}: {msg}")
            
        return True
        
    except Exception as e:
        print(f"❌ 管道测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 智谱AI图像生成测试")
    print("=" * 50)
    
    # 测试1: 直接API调用
    success1 = asyncio.run(test_zhipu_image_generation())
    
    # 测试2: 完整管道
    success2 = asyncio.run(test_full_pipeline_with_zhipu())
    
    print("\n📊 测试总结:")
    print(f"   直接API调用: {'✅ 成功' if success1 else '❌ 失败'}")
    print(f"   完整管道测试: {'✅ 成功' if success2 else '❌ 失败'}")
    
    if success1 and success2:
        print("\n🎉 恭喜！智谱AI图像生成功能工作正常！")
        print("您现在可以通过语音指令 '帮我生成一张小猫的图片' 来使用此功能。")
    else:
        print("\n⚠️  测试中有部分失败，请检查配置和网络连接。")
    
    sys.exit(0 if (success1 and success2) else 1)