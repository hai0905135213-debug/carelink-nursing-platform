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
_basedir = os.path.abspath(os.path.dirname(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(_basedir, 'carelink.dev.db')}"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change")
AMAP_KEY = os.environ.get("AMAP_KEY", "67b5303d6e5df6b249332ca496266d44")

def now():
    return datetime.utcnow()
