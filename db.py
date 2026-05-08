from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from config import DATABASE_URL

# 创建 engine 与 session 工厂
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
Session = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

def db_session():
    return Session()

def init_db():
    import models  # noqa: F401
    Base.metadata.create_all(engine)

    # 统一的数据库迁移：为已有表添加新列（若列已存在则忽略错误）
    _alter_statements = [
        # orders 表
        "ALTER TABLE orders ADD COLUMN paid INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN acceptable_price_range VARCHAR(32)",
        "ALTER TABLE orders ADD COLUMN address VARCHAR(255)",
        "ALTER TABLE orders ADD COLUMN current_risk_level VARCHAR(16) DEFAULT 'low'",
        "ALTER TABLE orders ADD COLUMN risk_reason TEXT",
        "ALTER TABLE orders ADD COLUMN share_insurance_data INTEGER DEFAULT 0",
        # users 表
        "ALTER TABLE users ADD COLUMN hospital_proof_path VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN hospital_name VARCHAR(128)",
        "ALTER TABLE users ADD COLUMN longitude FLOAT",
        "ALTER TABLE users ADD COLUMN latitude FLOAT",
        "ALTER TABLE users ADD COLUMN service_radius INTEGER DEFAULT 5",
        # ratings 表
        "ALTER TABLE ratings ADD COLUMN score_attitude FLOAT",
        "ALTER TABLE ratings ADD COLUMN score_ability FLOAT",
        "ALTER TABLE ratings ADD COLUMN score_transparent FLOAT",
        # care_logs 表
        "ALTER TABLE care_logs ADD COLUMN photo_path VARCHAR(255)",
        "ALTER TABLE care_logs ADD COLUMN health_skin VARCHAR(32) DEFAULT '正常'",
        "ALTER TABLE care_logs ADD COLUMN health_mobility VARCHAR(32) DEFAULT '平稳'",
        "ALTER TABLE care_logs ADD COLUMN health_digestion VARCHAR(32) DEFAULT '正常'",
        "ALTER TABLE care_logs ADD COLUMN health_mental VARCHAR(32) DEFAULT '清醒'",
    ]
    for stmt in _alter_statements:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception:
            pass

    # 创建可能缺失的表
    _create_statements = [
        """CREATE TABLE IF NOT EXISTS binding_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            elder_id INTEGER NOT NULL,
            status VARCHAR(16) DEFAULT 'pending',
            message TEXT,
            created_at DATETIME,
            responded_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS order_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            worker_id INTEGER NOT NULL,
            status VARCHAR(16) DEFAULT 'pending',
            applied_at DATETIME,
            reviewed_at DATETIME
        )""",
    ]
    for stmt in _create_statements:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception:
            pass


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
