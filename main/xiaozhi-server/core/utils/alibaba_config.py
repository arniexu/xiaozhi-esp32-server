#!/usr/bin/env python3
"""
阿里云配置读取工具
从YAML配置文件读取阿里云相关配置，包括密钥、OSS等
同时设置环境变量以支持阿里云SDK
"""
import os
import yaml
from pathlib import Path

class AlibabaCloudConfig:
    def __init__(self, config_file="data/alibaba_cloud.yaml"):
        """
        初始化阿里云配置读取器
        @param config_file: 配置文件路径
        """
        # 获取项目根目录（xiaozhi-server目录）
        self.project_root = Path(__file__).parent.parent.parent
        self.config_file = self.project_root / config_file
        self.config_data = self._load_config()
        # 设置环境变量以支持阿里云SDK
        self._set_environment_variables()
    
    def _load_config(self):
        """
        加载配置文件
        @return: 配置数据字典
        """
        try:
            if not self.config_file.exists():
                print(f"⚠️  阿里云配置文件不存在: {self.config_file}")
                return {}
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                print(f"✅ 成功加载阿里云配置文件: {self.config_file}")
                return config
                
        except Exception as e:
            print(f"❌ 加载阿里云配置文件失败: {e}")
            return {}
    
    def _set_environment_variables(self):
        """
        设置环境变量以支持阿里云SDK
        """
        try:
            access_key_id = self.get_access_key_id()
            access_key_secret = self.get_access_key_secret()
            
            if access_key_id and access_key_secret:
                os.environ['ALIBABA_CLOUD_ACCESS_KEY_ID'] = access_key_id
                os.environ['ALIBABA_CLOUD_ACCESS_KEY_SECRET'] = access_key_secret
                print(f"✅ 已设置阿里云SDK环境变量")
            else:
                print(f"⚠️  无法设置阿里云SDK环境变量：密钥配置不完整")
                
        except Exception as e:
            print(f"❌ 设置阿里云SDK环境变量失败: {e}")
    
    def get_access_key_id(self):
        """获取Access Key ID"""
        return self.config_data.get('access_key_id', '')
    
    def get_access_key_secret(self):
        """获取Access Key Secret"""
        return self.config_data.get('access_key_secret', '')
    
    def get_facebody_endpoint(self):
        """获取人脸识别服务端点"""
        facebody = self.config_data.get('facebody', {})
        return facebody.get('endpoint', 'https://facebody.cn-shanghai.aliyuncs.com')
    
    def get_facebody_region(self):
        """获取人脸识别服务区域"""
        facebody = self.config_data.get('facebody', {})
        return facebody.get('region', 'cn-shanghai')
    
    def get_oss_endpoint(self):
        """获取OSS端点"""
        oss = self.config_data.get('oss', {})
        return oss.get('endpoint', 'https://oss-cn-shanghai.aliyuncs.com')
    
    def get_oss_bucket_name(self):
        """获取OSS存储桶名称"""
        oss = self.config_data.get('oss', {})
        return oss.get('bucket_name', 'faces-my-shanghai')
    
    def get_oss_region(self):
        """获取OSS区域"""
        oss = self.config_data.get('oss', {})
        return oss.get('region', 'cn-hangzhou')
    
    def is_configured(self):
        """检查是否已配置必要信息"""
        return bool(self.get_access_key_id() and self.get_access_key_secret())
    
    def get_masked_info(self):
        """获取脱敏后的配置信息，用于日志显示"""
        access_key_id = self.get_access_key_id()
        access_key_secret = self.get_access_key_secret()
        
        def mask_key(key):
            if not key or len(key) <= 8:
                return key
            return key[:4] + "*" * (len(key) - 8) + key[-4:]
        
        return {
            'access_key_id': mask_key(access_key_id),
            'access_key_secret': mask_key(access_key_secret),
            'facebody_endpoint': self.get_facebody_endpoint(),
            'oss_endpoint': self.get_oss_endpoint(),
            'oss_bucket_name': self.get_oss_bucket_name()
        }

# 全局配置实例
alibaba_config = AlibabaCloudConfig()
