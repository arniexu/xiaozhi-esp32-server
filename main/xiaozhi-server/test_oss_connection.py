#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试OSS连接和配置
"""

import os
import sys
import oss2
import base64
from alibabacloud_darabonba_env.client import Client as EnvClient

# OSS配置
FACEBODY_REGION = 'cn-shanghai'  # 人脸识别服务区域
OSS_REGION = 'cn-shanghai'  # OSS存储区域
OSS_BUCKET_NAME = 'faces-my-shanghai'
OSS_ENDPOINT = f'https://oss-{OSS_REGION}.aliyuncs.com'

def test_oss_connection():
    """测试OSS连接"""
    print("🧪 测试OSS连接")
    print("=" * 50)
    
    try:
        # 检查环境变量
        access_key_id = EnvClient.get_env('ALIBABA_CLOUD_ACCESS_KEY_ID')
        access_key_secret = EnvClient.get_env('ALIBABA_CLOUD_ACCESS_KEY_SECRET')
        
        if not access_key_id:
            print("❌ 错误: ALIBABA_CLOUD_ACCESS_KEY_ID 环境变量未设置")
            return False
            
        if not access_key_secret:
            print("❌ 错误: ALIBABA_CLOUD_ACCESS_KEY_SECRET 环境变量未设置")
            return False
            
        print(f"✅ 环境变量检查通过")
        print(f"   AccessKey ID: {access_key_id[:8]}...")
        print(f"   AccessKey Secret: {access_key_secret[:8]}...")
        
        # 初始化OSS客户端
        print(f"\n🔗 连接OSS服务")
        print(f"   Endpoint: {OSS_ENDPOINT}")
        print(f"   Bucket: {OSS_BUCKET_NAME}")
        
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET_NAME)
        
        # 测试bucket是否存在
        print(f"\n📦 检查Bucket是否存在...")
        try:
            bucket_info = bucket.get_bucket_info()
            print(f"✅ Bucket存在")
            print(f"   创建时间: {bucket_info.creation_date}")
            print(f"   存储类型: {bucket_info.storage_class}")
            print(f"   位置: {bucket_info.location}")
        except oss2.exceptions.NoSuchBucket:
            print(f"❌ 错误: Bucket '{OSS_BUCKET_NAME}' 不存在")
            print(f"💡 请登录OSS控制台创建bucket: https://oss.console.aliyun.com/")
            return False
        except Exception as e:
            print(f"❌ 检查Bucket失败: {str(e)}")
            return False
        
        # 测试上传一个小文件
        print(f"\n📤 测试文件上传...")
        test_content = "这是一个测试文件，用于验证OSS上传功能"
        test_key = "test/connection_test.txt"
        
        try:
            result = bucket.put_object(test_key, test_content.encode('utf-8'))
            if result.status == 200:
                print(f"✅ 文件上传成功")
                
                # 测试文件访问
                test_url = f"https://{OSS_BUCKET_NAME}.{OSS_ENDPOINT.replace('https://', '')}/{test_key}"
                print(f"   文件URL: {test_url}")
                
                # 清理测试文件
                bucket.delete_object(test_key)
                print(f"✅ 测试文件已清理")
                
            else:
                print(f"❌ 文件上传失败，状态码: {result.status}")
                return False
                
        except Exception as e:
            print(f"❌ 文件上传测试失败: {str(e)}")
            return False
        
        # 测试faces目录权限
        print(f"\n📁 测试faces目录...")
        faces_test_key = "faces/test_face.jpg"
        test_image_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\x9f\x00\x00\x00\x00\x01\x00\x01\x00\x00\x07\x06\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        
        try:
            result = bucket.put_object(faces_test_key, test_image_data)
            if result.status == 200:
                print(f"✅ faces目录访问正常")
                
                # 清理测试文件
                bucket.delete_object(faces_test_key)
                print(f"✅ 测试图片已清理")
            else:
                print(f"❌ faces目录测试失败，状态码: {result.status}")
                return False
                
        except Exception as e:
            print(f"❌ faces目录测试失败: {str(e)}")
            return False
        
        print(f"\n🎉 OSS连接测试全部通过！")
        print(f"💡 现在可以运行人脸识别测试了")
        return True
        
    except Exception as e:
        print(f"\n❌ OSS连接测试失败: {str(e)}")
        return False

def main():
    """主函数"""
    print("🚀 阿里云OSS连接测试")
    print("=" * 50)
    
    if test_oss_connection():
        print("\n✅ 测试完成 - 所有检查都通过了！")
        print("🚀 现在可以运行: python3 test_face_images.py")
    else:
        print("\n❌ 测试失败 - 请检查配置")
        print("💡 运行: bash setup_oss.sh 查看配置指南")

if __name__ == "__main__":
    main()
