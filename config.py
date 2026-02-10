"""
配置管理
从环境变量读取配置
"""
import os

class Config:
    # Jenkins 配置
    JENKINS_URL = os.getenv('JENKINS_URL', 'http://localhost:8080')
    JENKINS_API_TOKEN = os.getenv('JENKINS_API_TOKEN', '')
    JENKINS_USERNAME = os.getenv('JENKINS_USERNAME', '')
    
    # 飞书配置（默认使用指定 webhook，可通过环境变量覆盖）
    FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', 'https://open.feishu.cn/open-apis/bot/v2/hook/2f0c4e4e-763c-4dbc-90cc-5c8f91231dbd')
    # 发版计划列表/详情页基础 URL，用于飞书卡片「查看计划」链接（留空则仅文案，不生成可点击链接）
    APP_BASE_URL = os.getenv('APP_BASE_URL', '').rstrip('/')
    
    # 数据库配置
    DATABASE_PATH = os.getenv('DATABASE_PATH', '/data/release_plans.db')
    
    # 时区配置（统一使用东八区）
    TZ = os.getenv('TZ', 'Asia/Shanghai')
    
    # 轮询配置
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '20'))  # 秒
    POLL_TIMEOUT = int(os.getenv('POLL_TIMEOUT', '1800'))  # 秒，30分钟
    
    # 调度器配置
    SCHEDULER_INTERVAL = int(os.getenv('SCHEDULER_INTERVAL', '60'))  # 秒，每分钟扫描一次
    # 执行中超过该分钟数且全部未触发时发送飞书提醒
    STUCK_REMINDER_MINUTES = int(os.getenv('STUCK_REMINDER_MINUTES', '15'))
