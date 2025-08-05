#!/usr/bin/env python3
"""
测试配置文件读取功能
"""
import sys
import os

# 将项目根目录添加到Python路径
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main/xiaozhi-server'))

from core import conn

def mask_sensitive_info(value):
    """脱敏敏感信息"""
    if isinstance(value, str) and len(value) > 8:
        return value[:4] + "*" * (len(value) - 8) + value[-4:]
    return value

def test_config_reader():
    """测试配置读取功能"""
    print("🔧 测试配置文件读取功能...")
    
    try:
        # 测试读取阿里云配置
        alibaba_config = conn.config.get("alibaba_cloud", {})
        
        print(f"📋 阿里云配置:")
        print(f"  - access_key_id: {mask_sensitive_info(alibaba_config.get('access_key_id'))}")
        print(f"  - access_key_secret: {mask_sensitive_info(alibaba_config.get('access_key_secret'))}")
        print(f"  - endpoint: {alibaba_config.get('endpoint')}")
        
        oss_config = alibaba_config.get("oss", {})
        print(f"  - oss.endpoint: {oss_config.get('endpoint')}")
        print(f"  - oss.bucket_name: {oss_config.get('bucket_name')}")
        
        # 检查必要配置是否存在
        required_keys = ['access_key_id', 'access_key_secret']
        missing_keys = []
        
        for key in required_keys:
            if not alibaba_config.get(key):
                missing_keys.append(key)
        
        if missing_keys:
            print(f"❌ 缺少必要配置: {missing_keys}")
            print("💡 请在config.yaml中的alibaba_cloud节点下配置这些密钥")
            return False
        else:
            print("✅ 阿里云配置读取成功，必要密钥都已配置")
            return True
            
    except Exception as e:
        print(f"❌ 配置读取失败: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_config_reader()
    if success:
        print("\n🎉 配置读取测试通过!")
    else:
        print("\n💥 配置读取测试失败!")
        sys.exit(1)
