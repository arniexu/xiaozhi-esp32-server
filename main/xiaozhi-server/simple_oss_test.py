#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的OSS测试 - 检查bucket位置和连接
"""

import os
import oss2

# 配置
OSS_BUCKET_NAME = 'faces-my-shanghai'
OSS_REGION = 'cn-shanghai'
OSS_ENDPOINT = f'https://oss-{OSS_REGION}.aliyuncs.com'

def test_bucket_location():
    """检查bucket的实际位置"""
    print("🔍 检查OSS Bucket位置")
    print("=" * 50)
    
    try:
        # 获取环境变量
        access_key_id = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID')
        access_key_secret = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET')
        
        if not access_key_id or not access_key_secret:
            print("❌ 环境变量未设置")
            return
            
        print(f"📋 配置信息:")
        print(f"   Bucket: {OSS_BUCKET_NAME}")
        print(f"   预期区域: {OSS_REGION}")
        print(f"   Endpoint: {OSS_ENDPOINT}")
        print()
        
        # 创建认证对象
        auth = oss2.Auth(access_key_id, access_key_secret)
        
        # 创建bucket对象
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
        
        # 获取bucket信息
        try:
            bucket_info = bucket.get_bucket_info()
            print(f"✅ Bucket存在")
            print(f"   实际位置: {bucket_info.location}")
            print(f"   创建时间: {bucket_info.creation_date}")
            print(f"   存储类型: {bucket_info.storage_class}")
            
            # 检查区域是否匹配
            if bucket_info.location == OSS_REGION:
                print(f"✅ 区域匹配: {bucket_info.location}")
            else:
                print(f"❌ 区域不匹配!")
                print(f"   预期: {OSS_REGION}")
                print(f"   实际: {bucket_info.location}")
                
        except oss2.exceptions.NoSuchBucket:
            print(f"❌ Bucket '{OSS_BUCKET_NAME}' 不存在")
        except Exception as e:
            print(f"❌ 获取bucket信息失败: {e}")
            
        # 测试简单上传
        print("\n🧪 测试文件上传...")
        test_content = b"test content"
        test_key = "test/simple_test.txt"
        
        try:
            result = bucket.put_object(test_key, test_content)
            if result.status == 200:
                print("✅ 上传成功")
                
                # 生成URL
                url = f"https://{OSS_BUCKET_NAME}.{OSS_ENDPOINT.replace('https://', '')}/{test_key}"
                print(f"📍 文件URL: {url}")
                
                # 删除测试文件
                bucket.delete_object(test_key)
                print("🗑️  测试文件已删除")
            else:
                print(f"❌ 上传失败: {result.status}")
                
        except Exception as e:
            print(f"❌ 上传测试失败: {e}")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    test_bucket_location()
