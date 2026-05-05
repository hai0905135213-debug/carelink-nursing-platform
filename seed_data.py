"""生成丰富的测试数据：账号、绑定、订单、日志、评分。"""
import sys, os, random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from db import db_session, engine
from models import User, Order, CareLog, OrderApplication, Rating, BindingRequest
from werkzeug.security import generate_password_hash

PWD = generate_password_hash("pass123")
now = datetime.utcnow()


def create_users(db):
    """创建 2 老人 + 2 护工 + 2 家属，跳过已存在的邮箱。"""
    users = {}

    # ── 老人 ──
    elders_data = [
        ("张桂芳", "elder_zhang@test.com", "13800001001"),
        ("刘德明", "elder_liu@test.com", "13800001002"),
    ]
    for name, email, phone in elders_data:
        u = db.query(User).filter_by(email=email).first()
        if not u:
            u = User(role="elder", name=name, email=email, phone=phone,
                     password_hash=PWD, elder_profile_complete=1)
            db.add(u)
            db.flush()
        users[f"elder_{name[0]}"] = u

    # ── 护工 ──
    workers_data = [
        ("陈晓丽", "worker_chen@test.com", "13800002001", 150, "喂药, 洗澡, 陪伴, 康复训练"),
        ("赵建国", "worker_zhao@test.com", "13800002002", 120, "翻身, 测血压, 陪伴, 擦洗"),
    ]
    for name, email, phone, price, skills in workers_data:
        u = db.query(User).filter_by(email=email).first()
        if not u:
            u = User(role="worker", name=name, email=email, phone=phone,
                     password_hash=PWD, price_per_hour=price, rating=round(random.uniform(4.2, 4.9), 1),
                     skills_display=skills)
            db.add(u)
            db.flush()
        users[f"worker_{name[0]}"] = u

    # ── 家属 ──
    families_data = [
        ("张小明", "family_zhang@test.com", "13800003001"),
        ("刘伟", "family_liu@test.com", "13800003002"),
    ]
    for name, email, phone in families_data:
        u = db.query(User).filter_by(email=email).first()
        if not u:
            u = User(role="family", name=name, email=email, phone=phone,
                     password_hash=PWD)
            db.add(u)
            db.flush()
        users[f"family_{name[0]}"] = u

    db.commit()
    return users


def create_bindings(db, users):
    """创建家属-老人绑定请求（含记录）。"""
    pairs = [
        ("family_张", "elder_张"),
        ("family_刘", "elder_刘"),
    ]
    for fam_key, elder_key in pairs:
        fam = users[fam_key]
        elder = users[elder_key]
        # 检查是否已有绑定
        existing = db.query(BindingRequest).filter_by(family_id=fam.id, elder_id=elder.id).first()
        if existing:
            continue
        req = BindingRequest(
            family_id=fam.id, elder_id=elder.id,
            status="accepted",
            message=f"我是{elder.name}的家属，希望绑定照护账号",
            created_at=now - timedelta(days=30),
            responded_at=now - timedelta(days=29)
        )
        db.add(req)
        fam.bound_elder_id = elder.id
    db.commit()


def create_orders_and_logs(db, users):
    """创建多种状态的订单、日志、申请、评分。"""
    elder_z = users["elder_张"]
    elder_l = users["elder_刘"]
    worker_c = users["worker_陈"]
    worker_z = users["worker_赵"]

    orders_config = [
        # ── 老人张桂芳的订单 ──
        {
            "elder": elder_z, "worker": worker_c,
            "title": "日常陪护与用药管理",
            "desc": "每日早晚协助服药，陪伴聊天，简单擦洗。老人患有轻度高血压，需定时测量血压。",
            "skills": "喂药, 陪伴, 测血压", "price": "100-160",
            "status": "in_progress", "risk": "low", "risk_reason": "",
            "days_ago": 10, "log_count": 8, "high_risk_log": False,
        },
        {
            "elder": elder_z, "worker": None,
            "title": "术后康复护理",
            "desc": "老人髋关节置换术后第5天，需专业康复师协助下床行走、伤口观察、换药。有糖尿病史，需监测血糖。",
            "skills": "康复训练, 换药, 测血糖, 翻身", "price": "180-250",
            "status": "open", "risk": "medium", "risk_reason": "术后恢复期，存在感染和跌倒风险",
            "days_ago": 2, "log_count": 0, "high_risk_log": False,
        },
        {
            "elder": elder_z, "worker": worker_c,
            "title": "全天候重症陪护",
            "desc": "老人突发脑梗后遗症，左侧偏瘫，吞咽困难，需24小时陪护。鼻饲管护理，定时翻身拍背，防褥疮。",
            "skills": "翻身, 鼻饲, 擦洗, 陪伴, 康复训练", "price": "200-300",
            "status": "in_progress", "risk": "high", "risk_reason": "脑梗后遗症伴吞咽障碍，存在误吸和褥疮高风险",
            "days_ago": 15, "log_count": 12, "high_risk_log": True,
        },
        {
            "elder": elder_z, "worker": worker_c,
            "title": "短期日间照料",
            "desc": "家属出差期间需要日间照料老人，协助午餐、午休、简单活动。",
            "skills": "陪伴, 喂饭", "price": "80-120",
            "status": "completed", "risk": "low", "risk_reason": "",
            "days_ago": 30, "log_count": 5, "high_risk_log": False,
        },

        # ── 老人刘德明的订单 ──
        {
            "elder": elder_l, "worker": worker_z,
            "title": "帕金森病日常护理",
            "desc": "老人帕金森病中期，肢体震颤明显，步态不稳。需协助进食、穿衣、如厕，防跌倒。每日记录震颤程度和用药反应。",
            "skills": "陪伴, 喂药, 翻身, 测血压", "price": "150-200",
            "status": "in_progress", "risk": "high", "risk_reason": "帕金森病中期，跌倒风险极高，需持续监护",
            "days_ago": 20, "log_count": 15, "high_risk_log": True,
        },
        {
            "elder": elder_l, "worker": None,
            "title": "夜间陪护",
            "desc": "老人夜间频繁起夜，需协助如厕，防止跌倒。晚8点至早8点。",
            "skills": "陪伴, 翻身", "price": "120-180",
            "status": "open", "risk": "medium", "risk_reason": "夜间活动跌倒风险",
            "days_ago": 1, "log_count": 0, "high_risk_log": False,
        },
        {
            "elder": elder_l, "worker": worker_z,
            "title": "糖尿病足护理",
            "desc": "老人糖尿病20年，双足溃疡，需每日换药、观察伤口、血糖监测。足部护理需严格无菌操作。",
            "skills": "换药, 测血糖, 擦洗", "price": "160-220",
            "status": "handover", "risk": "high", "risk_reason": "糖尿病足溃疡感染风险，原护工离职需交接",
            "days_ago": 25, "log_count": 10, "high_risk_log": True,
            "handover_notes": "赵护工因个人原因离职。老人足部溃疡左脚较重，换药时需特别注意无菌操作。血糖波动较大，建议新护工每日测三次。",
        },
        {
            "elder": elder_l, "worker": worker_z,
            "title": "康复期营养照料",
            "desc": "老人骨折康复期，需高蛋白饮食搭配，协助进食和简单肢体活动。",
            "skills": "喂饭, 陪伴, 康复训练", "price": "100-150",
            "status": "completed", "risk": "low", "risk_reason": "",
            "days_ago": 45, "log_count": 6, "high_risk_log": False,
        },
    ]

    health_normal = {"skin": "正常", "mobility": "平稳", "digestion": "正常", "mental": "清醒"}
    health_sets_normal = [health_normal] * 8 + [
        {"skin": "正常", "mobility": "平稳", "digestion": "吞咽困难或拒食", "mental": "清醒"},
    ]
    health_sets_high = [
        {"skin": "局部泛红或破损", "mobility": "步态不稳或摔倒", "digestion": "吞咽困难或拒食", "mental": "嗜睡或认知模糊"},
        {"skin": "意外淤青", "mobility": "步态不稳或摔倒", "digestion": "正常", "mental": "清醒"},
        {"skin": "正常", "mobility": "长期卧床", "digestion": "连续便秘或腹泻", "mental": "嗜睡或认知模糊"},
        {"skin": "局部泛红或破损", "mobility": "长期卧床", "digestion": "吞咽困难或拒食", "mental": "清醒"},
        {"skin": "正常", "mobility": "步态不稳或摔倒", "digestion": "正常", "mental": "清醒"},
        {"skin": "正常", "mobility": "平稳", "digestion": "正常", "mental": "清醒"},
    ]
    anomaly_pool_high = [
        "老人今日左侧肢体活动明显减少，肌力评估约3级",
        "发现骶尾部皮肤发红，面积约3cm×3cm，已加强翻身频次",
        "鼻饲后出现呛咳，暂停鼻饲30分钟后缓解",
        "夜间烦躁不安，反复试图下床，已加装床栏",
        "血糖餐前12.8mmol/L，偏高，已通知医生调整胰岛素用量",
        "足部溃疡创面渗液增多，已拍照记录并报告主治医师",
        "今日吞咽功能较昨日稍有改善，可少量饮水",
        "老人情绪低落，拒绝进食，经安抚后勉强进食半碗粥",
    ]
    anomaly_pool_normal = [None, None, None, None, "老人今日心情较好", None]
    contents_normal = [
        "早间护理完成，协助洗漱、服药，血压135/85mmHg",
        "午间巡视，老人午睡中，翻身一次，皮肤完好",
        "协助午餐进食，食欲一般，进食约2/3份",
        "下午陪伴聊天30分钟，老人精神状态良好",
        "晚间擦洗完成，协助服药，无异常",
        "夜间巡视2次，老人睡眠尚可",
        "测量血压130/80mmHg，血糖6.2mmol/L，均在正常范围",
        "康复训练20分钟，协助站立和缓步行走",
    ]
    contents_high = [
        "晨间护理：协助翻身、擦洗，骶尾部皮肤发红区域较昨日稍有扩大",
        "鼻饲喂食200ml，过程中无呛咳，生命体征平稳",
        "康复训练：被动关节活动30分钟，左下肢肌力略有改善",
        "午后巡视：老人嗜睡状态，呼唤可唤醒，GCS评分14分",
        "协助服药，观察药物反应，未见明显不良反应",
        "发现老人左踝部新发淤青约2cm×2cm，原因不明，已记录并上报",
        "夜间巡视3次，老人烦躁不安，给予床栏保护",
        "血糖监测：空腹8.9mmol/L，餐后2h 13.2mmol/L，偏高",
        "足部换药：左足溃疡创面清洁，无脓性分泌物，覆盖新敷料",
        "老人今日情绪好转，主动要求下床活动，协助坐轮椅15分钟",
        "吞咽功能训练10分钟，可少量吞咽糊状食物",
        "拍背排痰，老人咳出少量黄痰，呼吸音较前改善",
    ]

    for cfg in orders_config:
        elder = cfg["elder"]
        worker = cfg.get("worker")
        # 检查订单是否已存在（按标题+老人去重）
        existing = db.query(Order).filter_by(elder_id=elder.id, title=cfg["title"]).first()
        if existing:
            continue

        o = Order(
            elder_id=elder.id,
            title=cfg["title"],
            description=cfg["desc"],
            skills_required=cfg["skills"],
            acceptable_price_range=cfg["price"],
            address="北京市朝阳区某某小区",
            status=cfg["status"],
            created_at=now - timedelta(days=cfg["days_ago"]),
            accepted_worker_id=worker.id if worker else None,
            current_risk_level=cfg["risk"],
            risk_reason=cfg["risk_reason"],
            handover_notes=cfg.get("handover_notes"),
            paid=1 if cfg["status"] == "completed" else 0,
        )
        db.add(o)
        db.flush()

        # 创建申请记录
        if worker and cfg["status"] in ("in_progress", "accepted", "completed", "handover"):
            app_row = OrderApplication(
                order_id=o.id, worker_id=worker.id,
                status="accepted",
                applied_at=now - timedelta(days=cfg["days_ago"]),
                reviewed_at=now - timedelta(days=cfg["days_ago"]) + timedelta(hours=2)
            )
            db.add(app_row)

        # 创建日志
        is_high = cfg["high_risk_log"]
        for i in range(cfg["log_count"]):
            day_offset = cfg["days_ago"] - i
            if day_offset < 0:
                continue
            if is_high:
                h = random.choice(health_sets_high)
                anomaly = random.choice(anomaly_pool_high) if random.random() < 0.5 else None
                content = random.choice(contents_high)
            else:
                h = random.choice(health_sets_normal)
                anomaly = random.choice(anomaly_pool_normal)
                content = random.choice(contents_normal)

            log = CareLog(
                order_id=o.id,
                worker_id=worker.id if worker else 1,
                content=content,
                anomalies=anomaly,
                duration_minutes=random.randint(30, 90),
                created_at=now - timedelta(days=day_offset, hours=random.randint(6, 20)),
                health_skin=h["skin"],
                health_mobility=h["mobility"],
                health_digestion=h["digestion"],
                health_mental=h["mental"],
            )
            db.add(log)

        # 已完成订单创建评分
        if cfg["status"] == "completed" and worker:
            r = Rating(
                order_id=o.id, worker_id=worker.id, rater_id=elder.id,
                score=round(random.uniform(4.0, 5.0), 1),
                score_attitude=round(random.uniform(4.0, 5.0), 1),
                score_ability=round(random.uniform(4.0, 5.0), 1),
                score_transparent=round(random.uniform(4.0, 5.0), 1),
                comment="服务态度好，护理专业，很满意。",
                created_at=now - timedelta(days=cfg["days_ago"] - 1)
            )
            db.add(r)

    db.commit()


def main():
    from db import Session
    db = Session()
    try:
        print("创建用户...")
        users = create_users(db)
        print(f"  用户创建完成，共 {len(users)} 个")

        print("创建家属-老人绑定...")
        create_bindings(db, users)
        print("  绑定创建完成")

        print("创建订单、日志、评分...")
        create_orders_and_logs(db, users)
        print("  订单数据创建完成")

        # 统计
        print("\n=== 数据统计 ===")
        print(f"用户总数: {db.query(User).count()}")
        print(f"  老人: {db.query(User).filter_by(role='elder').count()}")
        print(f"  护工: {db.query(User).filter_by(role='worker').count()}")
        print(f"  家属: {db.query(User).filter_by(role='family').count()}")
        print(f"绑定请求数: {db.query(BindingRequest).count()}")
        print(f"订单总数: {db.query(Order).count()}")
        for status in ['open', 'in_progress', 'completed', 'handover']:
            cnt = db.query(Order).filter_by(status=status).count()
            print(f"  {status}: {cnt}")
        print(f"护理日志数: {db.query(CareLog).count()}")
        print(f"评分数: {db.query(Rating).count()}")
        print(f"申请数: {db.query(OrderApplication).count()}")

        print("\n=== 测试账号（密码均为 123456）===")
        for u in db.query(User).order_by(User.id).all():
            bind = f" → 老人ID{u.bound_elder_id}" if u.bound_elder_id else ""
            print(f"  [{u.role:6s}] {u.name}  {u.email}{bind}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
