import os
from datetime import datetime

# 状态映射：将内部状态码映射为中文展示文本
STATUS_MAP = {
  'open': '待接单',
  'in_progress': '进行中',
  'completed': '已完成',
  'handover': '待接手'
}

def status_label(s):
  return STATUS_MAP.get(s, s)

# 数据库与密钥配置：优先从环境变量读取
DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///carelink.dev.db"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change")

def now():
    return datetime.utcnow()
