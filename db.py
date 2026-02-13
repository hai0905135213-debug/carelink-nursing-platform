from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from config import DATABASE_URL

# 创建 engine 与 session 工厂
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
Session = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

def db_session():
    return Session()

def init_db():
    # 延迟导入 models，避免循环导入问题
    # 导入 models 模块以注册所有模型到 Base，然后创建表
    import models  # noqa: F401
    Base.metadata.create_all(engine)


def seed():
    """向数据库插入示例数据（仅在显式调用时运行）。"""
    from werkzeug.security import generate_password_hash
    # 延迟导入 models，避免循环导入
    from models import User, Order, CareLog

    db = Session()
    try:
        if db.query(User).count() == 0:
            w = User(role="worker", name="护工小李", email="worker@hlzl.test",
                     phone="18800001111", password_hash=generate_password_hash("pass123"),
                     price_per_hour=120, rating=4.8, skills_display="喂药, 洗澡, 陪伴")
            e = User(role="elder", name="王老先生", email="elder@hlzl.test",
                     phone="18800002222", password_hash=generate_password_hash("pass123"),
                     elder_profile_complete=1)
            f = User(role="family", name="家属李先生", email="family@hlzl.test",
                     phone="18800003333", password_hash=generate_password_hash("pass123"))
            db.add_all([w, e, f])
            db.commit()
            # 绑定并创建示例订单与日志
            f.bound_elder_id = e.id
            o = Order(elder_id=e.id, title="日常护理与陪伴",
                      description="每日晚餐前喂药，晚间简单擦洗与聊天半小时。",
                      skills_required="喂药, 陪伴", status="open")
            db.add(o)
            db.commit()
            log = CareLog(order_id=o.id, worker_id=w.id,
                         content="今日喂药顺利完成，老人精神状态良好",
                         anomalies="无异常", duration_minutes=45)
            db.add(log)
            db.commit()
            print("[db.seed] 数据库已初始化，测试账号已创建。")
    except Exception as e:
        print(f"[db.seed] 数据库初始化失败: {e}")
        db.rollback()
    finally:
        db.close()
