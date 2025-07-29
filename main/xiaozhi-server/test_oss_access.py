#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试OSS图片URL是否可以被阿里云人脸识别服务访问
"""

import os
import oss2
import base64
import requests
import time

# 配置
OSS_BUCKET_NAME = 'faces-my-shanghai'
OSS_ENDPOINT = 'https://oss-cn-shanghai.aliyuncs.com'

def test_oss_image_access():
    """测试OSS图片URL访问"""
    print("🔍 测试OSS图片URL访问权限")
    print("=" * 50)
    
    try:
        # 获取环境变量
        access_key_id = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID')
        access_key_secret = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET')
        
        if not access_key_id or not access_key_secret:
            print("❌ 环境变量未设置")
            return
            
        # 创建认证对象
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
        
        # 创建一个测试图片（简单的白色方块）
        test_image_data = base64.b64decode('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwA/8A8A')
        
        # 上传测试图片
        test_key = f"test/test_image_{int(time.time())}.jpg"
        result = bucket.put_object(test_key, test_image_data)
        
        if result.status == 200:
            print("✅ 测试图片上传成功")
            
            # 生成URL
            url = f"https://{OSS_BUCKET_NAME}.oss-cn-shanghai.aliyuncs.com/{test_key}"
            print(f"📍 图片URL: {url}")
            
            # 检查bucket权限设置
            print("\n🔐 检查Bucket权限...")
            try:
                bucket_acl = bucket.get_bucket_acl()
                print(f"   Bucket ACL: {bucket_acl.acl}")
            except Exception as e:
                print(f"   获取ACL失败: {e}")
            
            # 尝试直接访问URL
            print("\n🌐 测试URL直接访问...")
            try:
                response = requests.get(url, timeout=10)
                print(f"   HTTP状态码: {response.status_code}")
                if response.status_code == 200:
                    print("   ✅ URL可以直接访问")
                elif response.status_code == 403:
                    print("   ❌ 403 Forbidden - 需要设置bucket为公开读取")
                else:
                    print(f"   ❌ 访问失败: {response.status_code}")
            except Exception as e:
                print(f"   ❌ URL访问测试失败: {e}")
            
            # 生成签名URL
            print("\n🔗 生成签名URL...")
            try:
                signed_url = bucket.sign_url('GET', test_key, 3600)  # 1小时有效
                print(f"   签名URL: {signed_url[:100]}...")
                
                response = requests.get(signed_url, timeout=10)
                print(f"   签名URL状态码: {response.status_code}")
                if response.status_code == 200:
                    print("   ✅ 签名URL可以访问")
                else:
                    print(f"   ❌ 签名URL访问失败: {response.status_code}")
            except Exception as e:
                print(f"   ❌ 签名URL测试失败: {e}")
            
            # 清理测试文件
            try:
                bucket.delete_object(test_key)
                print("\n🗑️  测试文件已删除")
            except:
                pass
                
        else:
            print(f"❌ 上传失败: {result.status}")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    test_oss_image_access()
