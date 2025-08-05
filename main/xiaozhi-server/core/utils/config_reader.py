"""配置文件读取工具"""
import os
from pathlib import Path

class ConfigReader:
    """从配置文件读取配置的工具类"""
    
    def __init__(self, config_file=None):
        if config_file is None:
            # 默认配置文件路径
            current_dir = Path(__file__).parent
            config_file = current_dir / "data" / ".env"
        
        self.config_file = Path(config_file)
        self.config = {}
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        if not self.config_file.exists():
            print(f"配置文件不存在: {self.config_file}")
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释行
                    if not line or line.startswith('#'):
                        continue
                    
                    # 解析键值对
                    if '=' in line:
                        key, value = line.split('=', 1)
                        self.config[key.strip()] = value.strip()
        
        except Exception as e:
            print(f"读取配置文件失败: {e}")
    
    def get(self, key, default=None):
        """获取配置值"""
        return self.config.get(key, default)
    
    def get_alibaba_cloud_config(self):
        """获取阿里云相关配置"""
        return {
            'access_key_id': self.get('ALIBABA_CLOUD_ACCESS_KEY_ID'),
            'access_key_secret': self.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET'),
            'oss_endpoint': self.get('ALIBABA_CLOUD_OSS_ENDPOINT'),
            'oss_bucket': self.get('ALIBABA_CLOUD_OSS_BUCKET'),
            'facebody_endpoint': self.get('ALIBABA_CLOUD_FACEBODY_ENDPOINT')
        }

# 全局配置实例
config_reader = ConfigReader()
