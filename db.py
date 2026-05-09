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
        "ALTER TABLE orders ADD COLUMN longitude FLOAT",
        "ALTER TABLE orders ADD COLUMN latitude FLOAT",
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
    from models import User, Order, CareLog, OrderApplication, Rating
    import datetime

    db = Session()
    try:
        if db.query(User).count() > 0:
            print("[db.seed] 数据库已有数据，跳过。")
            db.close()
            return

        pw = generate_password_hash
        # ============================================================
        # 第一批：原始测试账号（密码 pass123）
        # ============================================================
        # --- 老人 ---
        elder_wang = User(role="elder", name="王老先生", email="elder@hlzl.test",
                          phone="18800002222", password_hash=pw("pass123"),
                          elder_profile_complete=1)
        elder_huang = User(role="elder", name="黄老先生", email="elderh@hlzl.test",
                           phone="18800003333", password_hash=pw("pass123"),
                           elder_profile_complete=1)
        elder_zhao = User(role="elder", name="赵老先生", email="elderz@hlzl.test",
                          phone="18800004444", password_hash=pw("pass123"),
                          elder_profile_complete=1)

        # --- 护工 ---
        worker_li = User(role="worker", name="护工小李", email="worker@hlzl.test",
                         phone="18800001111", password_hash=pw("pass123"),
                         price_per_hour=120, rating=4.8, skills_display="喂药, 洗澡, 陪伴, 翻身")
        worker_tang = User(role="worker", name="唐护工", email="workert@hlzl.test",
                           phone="18800005555", password_hash=pw("pass123"),
                           price_per_hour=100, rating=4.5, skills_display="康复训练, 测血压, 测血糖")
        worker_sun = User(role="worker", name="孙护工", email="workers@hlzl.test",
                          phone="18800006666", password_hash=pw("pass123"),
                          price_per_hour=130, rating=4.7, skills_display="重症陪护, 压疮护理, 鼻饲")
        worker_li2 = User(role="worker", name="李护工", email="workerl@hlzl.test",
                          phone="18800007777", password_hash=pw("pass123"),
                          price_per_hour=110, rating=4.3, skills_display="陪伴, 喂药, 洗澡")
        worker_yao = User(role="worker", name="姚护工", email="workery@hlzl.test",
                          phone="18800008888", password_hash=pw("pass123"),
                          price_per_hour=140, rating=4.9, skills_display="术后护理, 康复训练, 压疮预防")

        # --- 家属 ---
        family_li = User(role="family", name="家属李先生", email="family@hlzl.test",
                         phone="18800009999", password_hash=pw("pass123"))
        family_xiao = User(role="family", name="肖家属", email="familyx@hlzl.test",
                           phone="18800010000", password_hash=pw("pass123"))
        family_qian = User(role="family", name="钱家属", email="familyq@hlzl.test",
                           phone="18800011111", password_hash=pw("pass123"))

        # ============================================================
        # 第二批：新增测试账号（密码 123456）
        # ============================================================
        elder_zhang = User(role="elder", name="张桂芳", email="elder_zhang@test.com",
                           phone="18800020001", password_hash=pw("123456"),
                           elder_profile_complete=1)
        elder_liu = User(role="elder", name="刘德明", email="elder_liu@test.com",
                         phone="18800020002", password_hash=pw("123456"),
                         elder_profile_complete=1)
        worker_chen = User(role="worker", name="陈晓丽", email="worker_chen@test.com",
                           phone="18800020003", password_hash=pw("123456"),
                           price_per_hour=115, rating=4.6, skills_display="喂药, 测血压, 陪伴")
        worker_zhao = User(role="worker", name="赵建国", email="worker_zhao@test.com",
                           phone="18800020004", password_hash=pw("123456"),
                           price_per_hour=125, rating=4.4, skills_display="康复训练, 测血糖, 洗澡")
        family_zhang = User(role="family", name="张小明", email="family_zhang@test.com",
                            phone="18800020005", password_hash=pw("123456"))
        family_liu = User(role="family", name="刘伟", email="family_liu@test.com",
                          phone="18800020006", password_hash=pw("123456"))

        all_users = [
            elder_wang, elder_huang, elder_zhao, elder_zhang, elder_liu,
            worker_li, worker_tang, worker_sun, worker_li2, worker_yao, worker_chen, worker_zhao,
            family_li, family_xiao, family_qian, family_zhang, family_liu
        ]
        db.add_all(all_users)
        db.commit()

        # ============================================================
        # 绑定关系：家属 → 老人
        # ============================================================
        family_li.bound_elder_id = elder_wang.id        # 李先生 → 王老先生
        family_xiao.bound_elder_id = elder_huang.id      # 肖家属 → 黄老先生
        family_zhang.bound_elder_id = elder_zhang.id     # 张小明 → 张桂芳
        family_liu.bound_elder_id = elder_liu.id         # 刘伟 → 刘德明
        db.commit()

        # ============================================================
        # 订单数据
        # ============================================================
        # --- 待接单 (open) ---
        o1 = Order(elder_id=elder_wang.id, title="术后康复护理",
                   description="髋关节置换术后，需每日康复训练与伤口观察，约2小时/天。",
                   skills_required="康复训练, 测血压", status="open",
                   acceptable_price_range="100-140")
        o2 = Order(elder_id=elder_huang.id, title="夜间陪护",
                   description="老人夜间需起夜2-3次，需协助如厕及防跌倒。晚8点至早6点。",
                   skills_required="陪伴, 翻身", status="open",
                   acceptable_price_range="80-120")

        # --- 进行中 (in_progress) ---
        o3 = Order(elder_id=elder_wang.id, title="日常护理与陪伴",
                   description="每日晚餐前喂药，晚间简单擦洗与聊天半小时。",
                   skills_required="喂药, 陪伴", status="in_progress",
                   accepted_worker_id=worker_li.id, acceptable_price_range="60-120")
        o4 = Order(elder_id=elder_huang.id, title="脑梗后遗症重症陪护",
                   description="吞咽障碍需鼻饲、每2小时翻身防褥疮、监测血压血氧。",
                   skills_required="重症陪护, 鼻饲, 压疮护理, 测血压", status="in_progress",
                   accepted_worker_id=worker_sun.id, acceptable_price_range="120-180",
                   current_risk_level="high", risk_reason="吞咽障碍、褥疮风险")
        o5 = Order(elder_id=elder_zhao.id, title="帕金森病护理",
                   description="协助服药、防跌倒、日常活动辅助。",
                   skills_required="陪伴, 喂药", status="in_progress",
                   accepted_worker_id=worker_tang.id, acceptable_price_range="80-120",
                   current_risk_level="high", risk_reason="跌倒高风险")
        o6 = Order(elder_id=elder_zhang.id, title="日常血压血糖监测",
                   description="每日早晚各测一次血压血糖并记录。",
                   skills_required="测血压, 测血糖", status="in_progress",
                   accepted_worker_id=worker_chen.id, acceptable_price_range="60-100")
        o7 = Order(elder_id=elder_liu.id, title="洗澡与个人卫生协助",
                   description="老人行动不便，需协助洗澡、更衣、剪指甲等。",
                   skills_required="洗澡, 陪伴", status="in_progress",
                   accepted_worker_id=worker_zhao.id, acceptable_price_range="60-100")
        o8 = Order(elder_id=elder_wang.id, title="病重老人看护",
                   description="多器官功能减退，需24小时监护。",
                   skills_required="重症陪护, 测血压, 测血糖, 喂药", status="in_progress",
                   accepted_worker_id=worker_yao.id, acceptable_price_range="140-200",
                   current_risk_level="high", risk_reason="多项异常指标")

        # --- 待接手 (handover) ---
        o9 = Order(elder_id=elder_zhao.id, title="糖尿病足护理",
                   description="糖尿病足溃疡换药、血糖监测、协助胰岛素注射。",
                   skills_required="测血糖, 喂药", status="handover",
                   acceptable_price_range="100-140", current_risk_level="high",
                   risk_reason="感染风险、待交接")

        # --- 已完成 (completed) ---
        o10 = Order(elder_id=elder_huang.id, title="短期术后照护",
                    description="白内障术后一周照护，已康复。",
                    skills_required="陪伴, 喂药", status="completed",
                    accepted_worker_id=worker_tang.id, acceptable_price_range="80-120")
        o11 = Order(elder_id=elder_zhao.id, title="感冒期间护理",
                    description="感冒发烧期间临时照护3天，已痊愈。",
                    skills_required="测血压, 陪伴", status="completed",
                    accepted_worker_id=worker_li2.id, acceptable_price_range="60-100")
        o12 = Order(elder_id=elder_zhang.id, title="术后康复训练",
                    description="膝关节置换术后康复训练，已完成全部疗程。",
                    skills_required="康复训练, 陪伴", status="completed",
                    accepted_worker_id=worker_chen.id, acceptable_price_range="100-140")

        db.add_all([o1, o2, o3, o4, o5, o6, o7, o8, o9, o10, o11, o12])
        db.commit()

        # ============================================================
        # 护理日志（进行中 & 已完成的订单）
        # ============================================================
        now_utc = datetime.datetime.utcnow()
        logs = [
            CareLog(order_id=o3.id, worker_id=worker_li.id,
                    content="今日喂药顺利完成，老人精神状态良好。",
                    anomalies="无异常", duration_minutes=45),
            CareLog(order_id=o4.id, worker_id=worker_sun.id,
                    content="按时翻身4次，鼻饲营养液500ml，血压135/85。",
                    anomalies="骶尾部皮肤稍红，已加强翻身频率", duration_minutes=180),
            CareLog(order_id=o5.id, worker_id=worker_tang.id,
                    content="协助服药准时完成，搀扶散步15分钟。",
                    anomalies="无异常", duration_minutes=60),
            CareLog(order_id=o8.id, worker_id=worker_yao.id,
                    content="24小时监护，生命体征每4小时记录一次。",
                    anomalies="凌晨3点血压偏高(158/92)，已通知家属，30分钟后恢复至正常范围", duration_minutes=480),
            CareLog(order_id=o10.id, worker_id=worker_tang.id,
                    content="术后照护完成，按时滴眼药，已康复。",
                    anomalies="无异常", duration_minutes=40),
            CareLog(order_id=o11.id, worker_id=worker_li2.id,
                    content="每日测体温血压，按时服药，3天后退烧痊愈。",
                    anomalies="无异常", duration_minutes=35),
        ]
        db.add_all(logs)
        db.commit()

        # ============================================================
        # 评分记录（已完成的订单）
        # ============================================================
        ratings = [
            Rating(order_id=o10.id, worker_id=worker_tang.id, rater_id=elder_huang.id,
                   score=4.2, score_attitude=4.5, score_ability=4.0, score_transparent=4.0,
                   comment="唐护工态度很好，就是专业方面还可以再提升。"),
            Rating(order_id=o11.id, worker_id=worker_li2.id, rater_id=elder_zhao.id,
                   score=4.0, score_attitude=4.0, score_ability=4.5, score_transparent=3.5,
                   comment="做事利索，但沟通不算特别透明。"),
            Rating(order_id=o12.id, worker_id=worker_chen.id, rater_id=elder_zhang.id,
                   score=4.8, score_attitude=5.0, score_ability=4.5, score_transparent=5.0,
                   comment="陈晓丽护工非常专业，康复训练很到位！"),
        ]
        db.add_all(ratings)
        db.commit()

        # ============================================================
        # 申请记录（让老人端「已申请护工」页面有数据可看）
        # ============================================================
        apps = [
            OrderApplication(order_id=o1.id, worker_id=worker_tang.id, status="pending",
                             applied_at=now_utc - datetime.timedelta(hours=2)),
            OrderApplication(order_id=o1.id, worker_id=worker_li2.id, status="pending",
                             applied_at=now_utc - datetime.timedelta(hours=5)),
            OrderApplication(order_id=o1.id, worker_id=worker_chen.id, status="pending",
                             applied_at=now_utc - datetime.timedelta(days=1)),
            OrderApplication(order_id=o2.id, worker_id=worker_sun.id, status="pending",
                             applied_at=now_utc - datetime.timedelta(hours=3)),
            OrderApplication(order_id=o2.id, worker_id=worker_zhao.id, status="pending",
                             applied_at=now_utc - datetime.timedelta(hours=8)),
        ]
        db.add_all(apps)
        db.commit()

        print("[db.seed] 数据库已初始化：17 个用户、12 个订单、6 条护理日志、3 条评分、5 条申请记录。")

    except Exception as e:
        print(f"[db.seed] 数据库初始化失败: {e}")
        db.rollback()
    finally:
        db.close()
