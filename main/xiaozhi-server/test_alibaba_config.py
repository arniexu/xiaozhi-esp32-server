#!/usr/bin/env python3
"""
测试阿里云配置读取功能
"""
import sys
import os

# 将项目根目录添加到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_alibaba_config():
    """测试阿里云配置读取功能"""
    print("🔧 测试阿里云配置读取功能...")
    
    try:
        from core.utils.alibaba_config import alibaba_config
        
        print(f"📋 配置文件路径: {alibaba_config.config_file}")
        print(f"📋 配置是否完整: {'是' if alibaba_config.is_configured() else '否'}")
        
        # 显示脱敏后的配置信息
        masked_info = alibaba_config.get_masked_info()
        print(f"📋 脱敏配置信息:")
        for key, value in masked_info.items():
            print(f"  - {key}: {value}")
        
        # 检查必要配置是否存在
        if not alibaba_config.is_configured():
            print("❌ 阿里云配置不完整")
            print("💡 请在data/alibaba_cloud.yaml中配置access_key_id和access_key_secret")
            return False
        else:
            print("✅ 阿里云配置读取成功，必要密钥都已配置")
            return True
            
    except Exception as e:
        print(f"❌ 配置读取失败: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_alibaba_config()
    if success:
        print("\n🎉 阿里云配置读取测试通过!")
    else:
        print("\n💥 阿里云配置读取测试失败!")
        sys.exit(1)
