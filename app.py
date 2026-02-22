import os
from datetime import datetime
import re
from collections import defaultdict
import json
import hashlib

from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# 本模块拆分：配置、DB、模型、表单
from config import SECRET_KEY, status_label, now, DATABASE_URL
from db import db_session, init_db, engine
from models import User, Order, CareLog
from forms import SKILL_CHOICES
from sqlalchemy import func, text

# -------------------- App/Ext -------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY
login_manager = LoginManager(app)
login_manager.login_view = "login"

# 姓氏展示：老人=姓氏+老先生，护工=姓氏+护工，家属=姓氏+家属
# 兼容旧数据：已有后缀不重复添加；护工「护工+姓氏」格式转为「姓氏+护工」
def format_display_name(surname, role):
    if not surname:
        return '—'
    name = str(surname).strip()
    suffix = {'elder': '老先生', 'worker': '护工', 'family': '家属'}.get(role, '')
    if not suffix:
        return name
    if name.endswith(suffix):
        return name
    if role == 'worker' and name.startswith('护工'):
        name = name[2:].strip() or name
    return name + suffix

@app.context_processor
def inject_display():
    def display_name(user):
        if not user:
            return '—'
        return format_display_name(getattr(user, 'name', None), getattr(user, 'role', None))
    return dict(format_display_name=format_display_name, display_name=display_name)

# 注册全局 Jinja 变量
app.jinja_env.globals.update({
  'SKILL_CHOICES': SKILL_CHOICES,
  'now': datetime.utcnow,
  'status_label': status_label,
})

# 数据库迁移：确保新增列存在
def _run_migrations():
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE orders ADD COLUMN paid INTEGER DEFAULT 0"))
            conn.commit()
    except Exception:
        pass
    for col in ['score_attitude', 'score_ability', 'score_transparent']:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE ratings ADD COLUMN {col} FLOAT"))
                conn.commit()
        except Exception:
            pass
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN hospital_proof_path VARCHAR(255)"))
            conn.commit()
    except Exception:
        pass
_run_migrations()

# 模型、表单、DB 等已拆至 modules：models.py / forms.py / db.py

# -------------------- Login ---------------------
@login_manager.user_loader
def load_user(uid):
  db = db_session()
  try:
    return db.get(User, int(uid))
  finally:
    db.close()

# -------------------- Templates (inline) --------
BASE = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>护理智联</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Merriweather:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand fw-semibold text-primary" href="{{ url_for('index') }}">护理智联</a>
    <button class="navbar-toggler" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
    <div id="nav" class="collapse navbar-collapse">
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>
        {% if current_user.is_authenticated and current_user.role=='worker' %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('worker_orders') }}">我的接单</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('worker_profile') }}">我的资料</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('worker_available_orders') }}">可接订单</a></li>
        {% elif current_user.is_authenticated and current_user.role=='elder' %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('elder_create') }}">发布订单</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('elder_orders') }}">我的订单</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('elder_workers') }}">护工列表</a></li>
        {% elif current_user.is_authenticated and current_user.role=='family' %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('family_overview') }}">护理概览</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('family_bind') }}">绑定老人</a></li>
        {% endif %}
      </ul>
      <div class="d-flex">
        {% if current_user.is_authenticated %}
          <span class="me-3 align-self-center">{{ display_name(current_user) }}</span>
          <a class="btn btn-outline-primary" href="{{ url_for('logout') }}">退出</a>
        {% else %}
          <a class="btn btn-primary" href="{{ url_for('login') }}">登录 / 注册</a>
        {% endif %}
      </div>
    </div>
  </div>
</nav>

<main class="container py-4">
  {% with msgs = get_flashed_messages(with_categories=true) %}
    {% for c,m in msgs %}
    <div class="alert alert-{{c}} alert-dismissible fade show" role="alert">
      {{m}}
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>
    {% endfor %}
  {% endwith %}
  {% block content %}{% endblock %}
</main>

<footer class="container py-4 small text-center border-top">
  © {{ now.year }} 护理智联 · 共享护理日志 · 任务接手 · 可视化 · 护工信息透明化
</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""

SAFETY = """
{% extends 'BASE' %}
{% block content %}
<div class="card p-4">
  <div class="d-flex align-items-center gap-3 mb-3">
    <div class="fs-4 fw-semibold">平台安全保障</div>
    <div class="text-secondary">我们致力于为用户与护工提供可信赖的服务体验</div>
  </div>

  <div class="row g-3">
    <div class="col-md-4">
      <div class="card p-3 h-100">
        <div class="d-flex align-items-center mb-2">
          <div class="me-3 stat-icon bg-gradient-primary"><i class="bi bi-shield-check fs-4"></i></div>
          <div>
            <div class="fw-semibold">护工资质认证</div>
            <div class="small text-secondary">所有护工通过身份与资质审核，凭证可查。</div>
          </div>
        </div>
        <ul class="small text-secondary">
          <li>身份证与从业证核验</li>
          <li>面试与背景核实</li>
          <li>定期培训记录</li>
        </ul>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card p-3 h-100">
        <div class="d-flex align-items-center mb-2">
          <div class="me-3 stat-icon bg-gradient-accent"><i class="bi bi-shield-lock fs-4"></i></div>
          <div>
            <div class="fw-semibold">服务与责任保险</div>
            <div class="small text-secondary">覆盖服务过程中的意外与责任赔付。</div>
          </div>
        </div>
        <div class="small text-secondary">针对不同服务等级，我们为用户与护工购买商业责任险，理赔通道透明。</div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card p-3 h-100">
        <div class="d-flex align-items-center mb-2">
          <div class="me-3 stat-icon" style="background:linear-gradient(90deg,#ffd166,#ff7a59)"><i class="bi bi-people-fill fs-4"></i></div>
          <div>
            <div class="fw-semibold">实时监控与日志共享</div>
            <div class="small text-secondary">护理日志与时间线对相关人可见，接手人员可无缝交接。</div>
          </div>
        </div>
        <div class="small text-secondary">护理时长、任务完成情况、交接备注都会被记录，支持导出。</div>
      </div>
    </div>
  </div>

  <hr class="my-4">
  <h6 class="mb-3">常见问题</h6>
  <div class="accordion" id="faq">
    <div class="accordion-item">
      <h2 class="accordion-header" id="q1"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#c1">护工如何通过认证？</button></h2>
      <div id="c1" class="accordion-collapse collapse" data-bs-parent="#faq"><div class="accordion-body">提交身份证与从业证，平台进行人工/自动核验并保留证照照片与审核记录。</div></div>
    </div>
    <div class="accordion-item">
      <h2 class="accordion-header" id="q2"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#c2">发生纠纷如何处理？</button></h2>
      <div id="c2" class="accordion-collapse collapse" data-bs-parent="#faq"><div class="accordion-body">平台提供调解通道，并根据情形启动保险理赔或第三方介入。</div></div>
    </div>
  </div>

  <div class="mt-4 d-flex gap-2">
    <a class="btn btn-primary" href="{{ url_for('index') }}">返回首页</a>
    <a class="btn btn-outline-secondary" href="mailto:support@example.com">联系客服</a>
  </div>
</div>
{% endblock %}
"""

HOME = """
{% extends 'BASE' %}
{% block content %}
<div class="hero mb-4">
  <div class="d-flex flex-column flex-md-row align-items-md-end justify-content-between">
    <div>
      <h2 class="fw-bold mb-1">护理智联 智慧护理平台</h2>
      <div class="opacity-75">共享护理日志 · 任务无缝接手 · 时间图表可视化 · 护工信息透明化</div>
    </div>
    <div class="mt-3 mt-md-0">
      {% if not current_user.is_authenticated %}
      <a class="btn btn-light me-2" href="{{ url_for('register') }}"><i class="bi bi-box-arrow-in-right me-1"></i>马上加入</a>
      {% endif %}
      <a class="btn btn-outline-light" href="{{ url_for('elder_create') if current_user.is_authenticated else url_for('login') }}"><i class="bi bi-plus-circle me-1"></i>发布护理订单</a>
    </div>
  </div>
</div>

<!-- Trust strip / quick stats -->
<div class="row g-3 mb-3">
  <div class="col-md-3"><div class="stat-mini"><div class="icon icon-verify bg-gradient-primary"><i class="bi bi-award"></i></div><div class="meta">已认证护工<div class="value">1,234</div></div></div></div>
  <div class="col-md-3"><div class="stat-mini"><div class="icon icon-insure bg-gradient-accent"><i class="bi bi-shield-check"></i></div><div class="meta">服务保障<div class="value">商业保险</div></div></div></div>
  <div class="col-md-3"><div class="stat-mini"><div class="icon icon-trace bg-gradient-primary"><i class="bi bi-journal-text"></i></div><div class="meta">共享日志<div class="value">可追溯</div></div></div></div>
  <div class="col-md-3"><div class="stat-mini"><div class="icon icon-trace bg-gradient-accent"><i class="bi bi-people-fill"></i></div><div class="meta">活跃用户<div class="value">5,678</div></div></div></div>
</div>

<div class="row g-4">
  <div class="col-md-4"><div class="card p-4 feature">
    <div class="d-flex align-items-center mb-2"><i class="bi bi-person-heart me-2"></i><h5 class="mb-0">专业护工</h5></div>
    <div class="text-secondary mb-3">持证上岗、经验丰富、专业背景审核</div>
    <a class="btn btn-sm btn-outline-primary" href="{{ url_for('elder_workers') if current_user.is_authenticated else url_for('login') }}">查看护工</a>
  </div></div>

  {% if not (current_user.is_authenticated and current_user.role=='worker') %}
  <div class="col-md-4"><div class="card p-4 feature">
    <div class="d-flex align-items-center mb-2"><i class="bi bi-clock-history me-2"></i><h5 class="mb-0">快速响应</h5></div>
    <div class="text-secondary mb-3">24小时在线，最快30分钟接单上门</div>
    <a class="btn btn-sm btn-primary" href="{{ url_for('elder_create') if current_user.is_authenticated else url_for('login') }}">立即预约</a>
  </div></div>
  {% endif %}

  <div class="col-md-4"><div class="card p-4 feature">
    <div class="d-flex align-items-center mb-2"><i class="bi bi-shield-check me-2"></i><h5 class="mb-0">安全保障</h5></div>
    <div class="text-secondary mb-3">全程保险保障，服务过程可追溯</div>
    <a class="btn btn-sm btn-outline-warning" href="{{ url_for('safety') }}">了解详情</a>
  </div></div>
</div>

<h5 class="section-title my-3">核心创新功能</h5>
<div class="row g-3 mb-4">
  <div class="col-md-3"><div class="card p-3 text-center">
    <i class="bi bi-journal-text text-primary mb-2" style="font-size: 2rem;"></i>
    <div class="fw-semibold">共享护理日志</div>
    <div class="small text-secondary">所有相关人员可查看完整护理记录</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <i class="bi bi-arrow-left-right text-primary mb-2" style="font-size: 2rem;"></i>
    <div class="fw-semibold">任务交接机制</div>
    <div class="small text-secondary">未完成任务自动暴露给其他护工</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <i class="bi bi-bar-chart text-primary mb-2" style="font-size: 2rem;"></i>
    <div class="fw-semibold">可视化图表</div>
    <div class="small text-secondary">护理时间数据可视化展示</div>
  </div></div>
  <div class="col-md-3"><div class="card p-3 text-center">
    <i class="bi bi-eye text-primary mb-2" style="font-size: 2rem;"></i>
    <div class="fw-semibold">信息透明化</div>
    <div class="small text-secondary">护工信息全面透明可查</div>
  </div></div>
</div>

  <div class="row g-4 mt-1">
  <div class="col-lg-8">
    <h5 class="section-title">服务项目</h5>
    <div class="row g-3">
      {% set colors = ['linear-gradient(90deg,#ffd166,#ff7a59)','linear-gradient(90deg,#1e6fff,#2fa66a)','linear-gradient(90deg,#8f7af6,#ff7a59)','linear-gradient(90deg,#4dd0e1,#1e6fff)'] %}
      {% for box in services %}
      {% set c = colors[loop.index0 % colors|length] %}
      <div class="col-md-6"><div class="card p-3">
        <div class="d-flex align-items-center mb-2">
          <span class="me-2" style="display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:10px;background:{{ c }};color:#fff;">
            <i class="bi {{ box.icon }}" style="font-size:1.1rem"></i>
          </span>
          <div class="fw-semibold" style="font-family: 'Merriweather', serif;">{{ box.title }}</div>
        </div>
        <ul class="list-dot text-secondary small mb-0">
          {% for li in box['items'] %}<li>{{ li }}</li>{% endfor %}
        </ul>
      </div></div>
      {% endfor %}
    </div>
  </div>
  <div class="col-lg-4">
    <h5 class="section-title">平台数据</h5>
    <div class="card p-3 stat-card">
      <div class="d-flex justify-content-between align-items-center border-bottom py-2">
        <div>已服务用户</div><div class="badge text-bg-primary">1,234</div>
      </div>
      <div class="d-flex justify-content-between align-items-center border-bottom py-2">
        <div>在岗护工</div><div class="badge text-bg-success">89</div>
      </div>
      <div class="d-flex justify-content-between align-items-center border-bottom py-2">
        <div>完成订单</div><div class="badge text-bg-warning">5,678</div>
      </div>
      <div class="d-flex justify-content-between align-items-center py-2">
        <div>平均响应时间</div><div class="badge text-bg-danger">25分钟</div>
      </div>
    </div>
  </div>
</div>

<h5 class="section-title my-3">最新护理订单</h5>
<div class="row g-3">
  {% for o in latest_orders %}
  <div class="col-md-4"><div class="card p-3 h-100">
    <div class="small text-secondary">发布者：{{ o.elder_name }}</div>
    <div class="fw-semibold mt-1">{{ o.title }}</div>
    <div class="small text-secondary">需：{{ o.skills_required }}</div>
    <div class="d-flex justify-content-between align-items-center mt-2">
      <span class="status-badge status-{{ o.status }}">{{ {'open':'待接单','in_progress':'进行中','completed':'已完成','handover':'待接手'}[o.status] }}</span>
      <a class="btn btn-sm btn-outline-primary" href="{{ url_for('order_detail', order_id=o.id) }}">详情</a>
    </div>
  </div></div>
  {% else %}
  <div class="text-secondary">暂无订单</div>
  {% endfor %}
</div>
{% endblock %}
"""

LOGIN = """
{% extends 'BASE' %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-5"><div class="card p-4">
    <h5 class="text-primary mb-3">登录 护理智联</h5>
    <form method="post">
      <div class="mb-3"><label class="form-label">邮箱</label><input class="form-control" name="email" type="email" required></div>
      <div class="mb-3"><label class="form-label">密码</label><input class="form-control" name="password" type="password" required></div>
      <button class="btn btn-primary w-100">登录</button>
    </form>
    <div class="small mt-2 text-secondary">没有账号？<a href="{{ url_for('register') }}">注册</a></div>
  </div></div>
</div>
{% endblock %}
"""

REGISTER = """
{% extends 'BASE' %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-lg-7"><div class="card p-4">
    <h5 class="text-primary mb-3">注册</h5>
    <form method="post">
      <div class="row g-3">
        <div class="col-md-4"><label class="form-label">角色</label>
          <select class="form-select" name="role" id="roleSelect">
            <option value="worker">护工</option><option value="elder">老人</option><option value="family">家属</option>
          </select></div>
        <div class="col-md-4"><label class="form-label">姓名</label><input class="form-control" name="name" required></div>
        <div class="col-md-4"><label class="form-label">邮箱</label><input class="form-control" name="email" type="email" required></div>
        <div class="col-md-4"><label class="form-label">电话</label><input class="form-control" name="phone"></div>
        <div class="col-md-4"><label class="form-label">密码</label><input class="form-control" name="password" type="password" required></div>
      </div>
      <hr class="my-3">
      <div class="row g-3" id="workerExtra">
        <div class="col-md-4"><label class="form-label">价格（每小时）</label><input class="form-control" type="number" step="0.01" name="price_per_hour" placeholder="120.00"></div>
        <div class="col-md-8"><label class="form-label">专业技能（多选）</label>
          <div class="d-flex flex-wrap gap-2">
            {% for s in skills %}<div class="form-check">
              <input class="form-check-input" type="checkbox" name="skills" value="{{ s }}" id="s{{ loop.index }}">
              <label class="form-check-label" for="s{{ loop.index }}">{{ s }}</label></div>{% endfor %}
          </div>
        </div>
      </div>
      <button class="btn btn-primary mt-3">注册</button>
    </form>
  </div></div>
</div>
<script>
const roleSel = document.getElementById('roleSelect'); const wExtra = document.getElementById('workerExtra');
function t(){ wExtra.style.display = roleSel.value==='worker' ? 'flex':'none'; } roleSel.addEventListener('change',t); t();
</script>
{% endblock %}
"""

ORDER_DETAIL = """
{% extends 'BASE' %}
{% block content %}
<div class="card p-4">
  <h5 class="mb-1">{{ o.title }}</h5>
  <div class="text-secondary small">发布者：{{ display_name(elder) }}</div>
  <div class="text-secondary small">需求：{{ o.skills_required or '—' }}</div>
  <div class="mt-2">{{ o.description }}</div>
  <div class="mt-3">
    <span class="status-badge status-{{ o.status }}">{{ {'open':'待接单','in_progress':'进行中','completed':'已完成','handover':'待接手'}[o.status] }}</span>
  {% if w %}<span class="badge rounded-pill text-bg-primary ms-2">护工：{{ display_name(w) }}</span>{% endif %}
  </div>
  {% if o.handover_notes %}
  <div class="alert alert-warning mt-3">
    <strong>交接备注：</strong>{{ o.handover_notes }}
  </div>
  {% endif %}
</div>
<div class="row g-3 mt-3">
  <div class="col-md-4">
    <div class="card p-3">
      <div class="fw-semibold mb-2">责任保险</div>
      <div class="small text-secondary">本订单支持商业责任险，理赔渠道透明。若需理赔请联系客服。</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card p-3">
      <div class="fw-semibold mb-2">交接记录</div>
      <div class="small text-secondary">以下为交接摘要（占位）：</div>
      <ul class="small text-secondary mt-2">
        <li>2026-02-10 10:00：李护工 完成早间护理</li>
        <li>2026-02-11 18:20：肖护工 交接并补充用药记录</li>
      </ul>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card p-3">
      <div class="fw-semibold mb-2">相关证书</div>
      <div class="small text-secondary">护工证书与培训记录（占位图）：</div>
      <div class="d-flex gap-2 mt-2">
        <div class="badge bg-light text-dark">身份证</div>
        <div class="badge bg-light text-dark">从业证</div>
        <div class="badge bg-light text-dark">急救证</div>
      </div>
    </div>
  </div>
</div>
<!-- 可视化区域：护理时长时序与护工时长占比 -->
<div class="row g-3 mt-4">
  <div class="col-md-8">
    <div class="card p-3">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <div class="fw-semibold">护理时长趋势（按日统计）</div>
        <div class="small text-secondary">单位：分钟</div>
      </div>
      <div class="chart-wrap position-relative">
        <canvas id="durationsChart" height="160" class="lazy-chart" data-order-id="{{ o.id }}"></canvas>
        <div class="chart-overlay" id="durationsChart-overlay">加载中...</div>
        <div class="chart-loader" id="durationsChart-loader"></div>
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card p-3">
      <div class="fw-semibold mb-2">护工时长占比</div>
      <div class="chart-wrap position-relative">
        <canvas id="workerShareChart" height="160" class="lazy-chart" data-order-id="{{ o.id }}"></canvas>
        <div class="chart-overlay d-none" id="workerShareChart-overlay">暂无数据</div>
        <div class="chart-loader d-none" id="workerShareChart-loader"></div>
      </div>
    </div>
  </div>
</div>

<!-- 懒加载钩子：当画布进入视口时加载静态脚本（只注入一次） -->
<script>
  window.ORDER_PAYLOAD = { orderId: {{ o.id }} };
  (function(){
    // 观察任意具有 .lazy-chart 的元素
    const toLoad = document.querySelectorAll('.lazy-chart');
    if(!toLoad.length) return;
    const loadOnce = ()=>{
      if(window.__analytics_loaded) return; window.__analytics_loaded = true;
      const s = document.createElement('script'); s.src = '/static/js/analytics.js'; s.defer = true; document.body.appendChild(s);
    };
    const obs = new IntersectionObserver((entries)=>{
      for(const e of entries){ if(e.isIntersecting){ loadOnce(); obs.disconnect(); break; } }
    }, {rootMargin: '200px'});
    toLoad.forEach(n=>obs.observe(n));
  })();
</script>
{% endblock %}
"""

WORKER_PROFILE = """
{% extends 'BASE' %}
{% block content %}
<h5 class="mb-3">我的资料</h5>
<form method="post" class="card p-4">
  <div class="row g-3">
    <div class="col-md-4"><label class="form-label">每小时价格</label>
      <input class="form-control" name="price_per_hour" type="number" step="0.01" value="{{ u.price_per_hour or '' }}" placeholder="120.00"></div>
    <div class="col-md-8"><label class="form-label">专业技能（多选）</label>
      <div class="d-flex flex-wrap gap-2">
        {% set skillset = (u.skills_display or '').split(', ') %}
        {% for s in skills %}<div class="form-check">
          <input class="form-check-input" type="checkbox" name="skills" value="{{ s }}" id="sk{{ loop.index }}" {% if s in skillset %}checked{% endif %}>
          <label class="form-check-label" for="sk{{ loop.index }}">{{ s }}</label></div>{% endfor %}
      </div>
    </div>
    <div class="col-md-12">
      <label class="form-label">联系方式</label>
      <input class="form-control" name="phone" value="{{ u.phone or '' }}">
    </div>
  </div>
  <button class="btn btn-primary mt-3">保存</button>
</form>
{% endblock %}
"""

WORKER_ORDERS = """
{% extends 'BASE' %}
{% block content %}
<h5 class="mb-2">我在做的订单</h5>
<div class="row g-3">
{% for o in my_orders %}
  <div class="col-md-6"><div class="card p-3">
    <div class="d-flex justify-content-between">
      <div class="fw-semibold">{{ o.title }}</div>
      <span class="status-badge status-{{ o.status }}">{{ {'open':'待接单','in_progress':'进行中','completed':'已完成','handover':'待接手'}[o.status] }}</span>
    </div>
    <div class="small text-secondary">老人：{{ o.elder_name }}</div>
    <div class="small text-secondary">需：{{ o.skills_required }}</div>
    <div class="d-flex gap-2 mt-2">
      <a class="btn btn-sm btn-outline-primary" href="{{ url_for('worker_log', order_id=o.id) }}">记录日志</a>
      <form method="post" action="{{ url_for('worker_handover', order_id=o.id) }}"><button class="btn btn-sm btn-outline-warning">标记待接手</button></form>
      <form method="post" action="{{ url_for('worker_complete', order_id=o.id) }}"><button class="btn btn-sm btn-success">完成订单</button></form>
    </div>
  </div></div>
{% else %}<div class="text-secondary">暂无进行中的订单</div>{% endfor %}
</div>

<h5 class="mt-4 mb-2">历史接单</h5>
<div class="row g-3">
{% for o in history_orders %}
  <div class="col-md-6"><div class="card p-3">
    <div class="fw-semibold">{{ o.title }}</div>
    <div class="small text-secondary">状态：{{ {'open':'待接单','in_progress':'进行中','completed':'已完成','handover':'待接手'}[o.status] }}</div>
    <div class="mt-2">
      <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('order_detail', order_id=o.id) }}">详情</a>
      <a class="btn btn-sm btn-outline-info" href="{{ url_for('elder_logs', order_id=o.id) }}">查看日志</a>
    </div>
  </div></div>
{% else %}<div class="text-secondary">暂无历史订单</div>{% endfor %}
</div>
{% endblock %}
"""

WORKER_AVAILABLE_ORDERS = """
{% extends 'BASE' %}
{% block content %}
<h5 class="mb-2">可接订单</h5>
<div class="row g-3">
{% for o in available %}
  <div class="col-md-6"><div class="card p-3">
    <div class="d-flex justify-content-between">
      <div class="fw-semibold">{{ o.title }}</div>
      <span class="status-badge status-{{ o.status }}">{{ {'open':'待接单','handover':'待接手'}[o.status] }}</span>
    </div>
    <div class="small text-secondary">老人：{{ o.elder_name }}</div>
    <div class="small text-secondary">需：{{ o.skills_required }}</div>
    {% if o.handover_notes %}
    <div class="alert alert-warning small py-1 my-2">
      <strong>交接备注：</strong>{{ o.handover_notes }}
    </div>
    {% endif %}
    <form class="mt-2" method="post" action="{{ url_for('worker_accept', order_id=o.id) }}">
      <button class="btn btn-sm btn-primary">接单</button>
      <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('order_detail', order_id=o.id) }}">详情</a>
      <a class="btn btn-sm btn-outline-info" href="{{ url_for('worker_preview_logs', order_id=o.id) }}">查看历史日志</a>
    </form>
  </div></div>
{% else %}<div class="text-secondary">暂无可接订单</div>{% endfor %}
</div>
{% endblock %}
"""

# 新增：护工公开页面模板（确保在引用前定义，避免 NameError）
WORKER_PUBLIC = """
{% extends 'BASE' %}
{% block content %}
<div class="card p-4">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <div class="fs-4 fw-semibold">{{ w.name }}</div>
      <div class="small text-secondary">评分：
        {% for i in range(1,6) %}
          {% if (w.rating or 0) >= i %}
            <i class="bi bi-star-fill text-warning"></i>
          {% elif (w.rating or 0) >= i-0.5 %}
            <i class="bi bi-star-half text-warning"></i>
          {% else %}
            <i class="bi bi-star text-muted"></i>
          {% endif %}
        {% endfor %}
        · {{ w.phone or '未公开' }}</div>
    </div>
    <div class="text-end">
      <div class="fw-semibold text-primary">¥{{ '%.0f'|format(w.price_per_hour or 0) }}/小时</div>
    </div>
  </div>

  <hr class="my-3">
  <div class="mb-2"><strong>专业技能</strong></div>
  <div class="text-secondary">{{ w.skills_display or '未填写' }}</div>

  <div class="mt-3">
    <div class="fw-semibold mb-2">证书与培训</div>
    <div class="d-flex gap-2">
      <div class="card p-2 text-center" style="min-width:120px"><div class="fw-semibold">从业证</div><div class="small text-secondary">已认证</div></div>
      <div class="card p-2 text-center" style="min-width:120px"><div class="fw-semibold">急救证</div><div class="small text-secondary">已完成</div></div>
    </div>
  </div>

  <div class="mt-3 d-flex gap-2">
    <a class="btn btn-primary" href="{{ url_for('index') }}">返回首页</a>
    {% if current_user.is_authenticated and current_user.role == 'family' %}
      <a class="btn btn-outline-primary" href="{{ url_for('family_overview') }}">查看绑定老人概览</a>
    {% endif %}
    {% if current_user.is_authenticated and current_user.role == 'elder' %}
      <a class="btn btn-sm btn-outline-secondary" href="#" onclick="alert('请在对应订单页面对护工进行评分');return false;">评价护工</a>
    {% endif %}
  </div>
</div>
{% endblock %}
"""

# 保底：如果因编辑顺序或未保存导致 WORKER_PUBLIC 不存在，使用此简易模板避免 NameError
if 'WORKER_PUBLIC' not in globals():
    WORKER_PUBLIC = """
    {% extends 'BASE' %}
    {% block content %}
    <div class="card p-4">
      <div class="fs-4 fw-semibold">护工信息</div>
      <div class="text-secondary">该页面模板暂不可用，请重启服务或联系管理员。</div>
      <div class="mt-3"><a class="btn btn-primary" href="{{ url_for('index') }}">返回首页</a></div>
    </div>
    {% endblock %}
    """

def _seeded_rng(seed):
    import random
    return random.Random(seed)

def _order_synth_durations(order_id, status, elder_id=0, days=14):
    """近 N 天护理时长合成数据。每个订单/老人随机不同（种子由 order_id + elder_id 决定）。

    进行中订单：前14天内随机选一天作为"开始日"，这天之前为0，从这天起有护理数据并持续到今天。
    待接单/待接手订单：前14天内随机选一天作为"断点"，这天之前有护理数据，从这天起为0（空窗期到今天）。
    """
    from datetime import timedelta
    today = datetime.utcnow().date()
    seed = order_id * 1007 + elder_id * 31
    rng = _seeded_rng(seed)
    synth = []

    if status in ('open', 'handover'):
        # 待接单/待接手：随机选一个"断点日"（距今 3~10 天前），断点当天及之后时长为 0
        cutoff_days_ago = rng.randint(3, 10)
        base_val = rng.randint(35, 75)
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            if i < cutoff_days_ago:
                # 断点之后（含当天）：空窗期
                minutes = 0
            else:
                # 断点之前：有护理数据
                minutes = base_val + rng.randint(-15, 20)
                minutes = max(20, min(120, minutes))
            synth.append({"date": str(d), "minutes": minutes})
    else:
        # 进行中/已接单：随机选一个"开始日"（距今 3~10 天前），开始日之前为0，从开始日起有数据
        start_days_ago = rng.randint(3, 10)
        base_val = rng.randint(40, 85)
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            if i > start_days_ago:
                # 开始日之前：无数据
                minutes = 0
            else:
                # 从开始日起：有护理数据
                minutes = base_val + rng.randint(-12, 18)
                minutes = max(25, min(110, minutes))
            synth.append({"date": str(d), "minutes": minutes})
    return synth


# -------------------- API -----------------------
@app.route("/api/order/<int:order_id>/durations")
def api_order_durations(order_id):
    db = db_session()
    try:
        o = db.get(Order, order_id)
        if not o:
            return jsonify(error="订单不存在"), 404
        # 合成数据（非隐私）允许任何登录用户查看；仅完成订单的真实日志需要权限
        status = getattr(o, 'status', 'open')
        if status == 'completed':
            if not current_user.is_authenticated:
                return jsonify(error="无权限访问该订单"), 403
            can_view = (o.elder_id == current_user.id or o.accepted_worker_id == current_user.id or
                        (require_family() and getattr(current_user, 'bound_elder_id', None) == o.elder_id))
            if not can_view:
                return jsonify(error="无权限访问该订单"), 403
        
        elder_id = getattr(o, 'elder_id', 0) or 0
        if status in ('open', 'handover'):
            return jsonify(_order_synth_durations(order_id, status, elder_id))
        if status in ('in_progress', 'accepted'):
            return jsonify(_order_synth_durations(order_id, status, elder_id))
        data = db.query(
            func.date(CareLog.created_at).label("date"),
            func.sum(CareLog.duration_minutes).label("minutes")
        ).filter(CareLog.order_id == order_id).group_by("date").all()
        result = [{"date": str(d.date), "minutes": d.minutes} for d in data]
        if not result:
            return jsonify(_order_synth_durations(order_id, status, elder_id))
        return jsonify(result)
    finally:
        db.close()

@app.route("/api/order/<int:order_id>/worker-shares")
def api_order_worker_shares(order_id):
    db = db_session()
    try:
        o = db.get(Order, order_id)
        if not o:
            return jsonify(error="订单不存在"), 404
        
        # 合成数据（非隐私）允许任何人查看；仅 completed 状态的真实数据做严格权限检查
        status = getattr(o, 'status', 'open')
        if status == 'completed':
            if not current_user.is_authenticated:
                return jsonify(error="无权限访问该订单"), 403
            can_view = (o.elder_id == current_user.id or 
                       o.accepted_worker_id == current_user.id or
                       (require_family() and getattr(current_user, 'bound_elder_id', None) == o.elder_id))
            if not can_view:
                return jsonify(error="无权限访问该订单"), 403
        
        # 查询该订单的护理记录，统计每位护工的服务时长
        data = db.query(
            CareLog.worker_id,
            func.sum(CareLog.duration_minutes).label("minutes")
        ).filter(CareLog.order_id == order_id).group_by(CareLog.worker_id).all()
        
        elder_id = getattr(o, 'elder_id', 0) or 0
        
        # 如果订单状态为 open 或 handover，生成与交接记录一致的模拟数据
        if status in ('open', 'handover'):
            seed = order_id * 1007 + elder_id * 31
            rng = _seeded_rng(seed)
            # 与 _order_synth_durations 和 order_detail 保持一致的调用顺序
            cutoff_days_ago = rng.randint(3, 10)
            _base_val = rng.randint(35, 75)

            # 用与 order_detail 相同的种子生成护工姓名
            log_rng = _seeded_rng(seed + 9999)
            surnames = ['李', '肖', '陈', '王', '张', '赵', '刘', '周', '吴', '郑', '孙', '马']
            idx = log_rng.sample(range(len(surnames)), 2)
            w1, w2 = surnames[idx[0]] + '护工', surnames[idx[1]] + '护工'
            logs = [
                {'worker_name': w1, 'duration_minutes': log_rng.randint(35, 55)},
                {'worker_name': w1, 'duration_minutes': log_rng.randint(22, 40)},
                {'worker_name': w2, 'duration_minutes': log_rng.randint(35, 50)},
                {'worker_name': w2, 'duration_minutes': log_rng.randint(25, 40)}
            ]
            worker_totals = {}
            for log in logs:
                name = log['worker_name']
                worker_totals[name] = worker_totals.get(name, 0) + log['duration_minutes']
            result = [{"worker": name, "minutes": total} for name, total in worker_totals.items()]
            return jsonify(result)
        
        if status in ('in_progress', 'accepted') and not data:
            seed = order_id * 1007 + elder_id * 31
            rng = _seeded_rng(seed + 1)
            surnames = ['李', '肖', '陈', '王', '张', '赵', '刘', '周', '吴', '郑']
            n = rng.sample(surnames, min(3, len(surnames)))
            names = [s + '护工' for s in n]
            vals = [rng.randint(20, 60) for _ in names]
            total = sum(vals)
            vals = [max(10, v * (100 + order_id % 50) // 100) for v in vals]
            return jsonify([{"worker": names[i], "minutes": vals[i]} for i in range(len(names))])
        
        workers_display = {u.id: format_display_name(u.name, 'worker') for u in db.query(User).filter(User.role == "worker").all()}
        result = [{"worker": workers_display.get(d.worker_id) or "护工", "minutes": d.minutes} for d in data]
        if not result:
          seed = order_id * 1007 + elder_id * 31
          rng = _seeded_rng(seed + 2)
          surnames = ['李', '肖', '陈', '王', '张', '赵']
          n = rng.sample(surnames, min(3, len(surnames)))
          names = [s + '护工' for s in n]
          vals = [rng.randint(15, 50) for _ in names]
          return jsonify([{"worker": names[i], "minutes": vals[i]} for i in range(len(names))])
        return jsonify(result)
    finally:
        db.close()

@app.route("/api/order/<int:order_id>/ai-report")
def api_order_ai_report(order_id):
    from openai import OpenAI
    import json
    db = db_session()
    try:
        o = db.get(Order, order_id)
        if not o:
            return jsonify(error="订单不存在"), 404
        
        # 提取护理日志
        logs = db.query(CareLog).filter(CareLog.order_id == order_id).order_by(CareLog.created_at.desc()).limit(14).all()
        log_texts = [f"{l.created_at.strftime('%Y-%m-%d %H:%M')}: {l.content}" for l in logs]
        
        # 获取老人姓名
        elder = db.get(User, getattr(o, 'elder_id', 0) or 0)
        elder_name = format_display_name(getattr(elder, 'name', ''), getattr(elder, 'role', 'elder')) if elder else "老人"
        
        if not log_texts:
            log_texts = ["暂无日志记录，老人状态平稳。"]
            
        client = OpenAI(api_key="sk-259952b41ae24b1e80c26ceaba58f778", base_url="https://api.deepseek.com")
        
        prompt = f"""
你是一个专业的AI医护助手。请基于以下最近14天的护理日志，生成一份针对这名老人({elder_name})的健康关怀报告。
护理日志:
{chr(10).join(log_texts)}

请严格按以下JSON格式返回，不要包含任何Markdown标记（不要输出```json等），只要输出纯JSON对象：
{{
  "summary": "一段对于老人健康温暖一点的文字总结",
  "suggestions": [
    "建议1（例如下次护理建议）",
    "建议2",
    "建议3"
  ],
  "abnormality": {{
    "level": "green(状况好或无日志) 或 yellow(轻微异常) 或 red(较严重异常)",
    "text": "简短描述，例如'无异常情况'或'轻度呼吸问题'"
  }},
  "tomorrow_advice": "明日关怀建议"
}}
"""
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        try:
            content = content.replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
        except Exception:
            data = {
                "summary": "今日状态平稳，生活起居正常，感谢您的关照。",
                "suggestions": ["注意保暖，避免着凉", "饮食宜清淡，易消化", "适当进行室内走动"],
                "abnormality": {"level": "green", "text": "无异常情况"},
                "tomorrow_advice": "建议明日继续观察睡眠情况，确保休息充足。"
            }
        
        data["elder_name"] = elder_name
        return jsonify(data)
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        db.close()

@app.route("/api/elder/<int:elder_id>/ai-report")
def api_elder_ai_report(elder_id):
    from openai import OpenAI
    import json
    db = db_session()
    try:
        if not current_user.is_authenticated:
            return jsonify(error="未登录"), 401
            
        # Permission check
        can_view = False
        if getattr(current_user, 'role', '') == 'elder' and current_user.id == elder_id:
            can_view = True
        elif getattr(current_user, 'role', '') == 'family' and getattr(current_user, 'bound_elder_id', None) == elder_id:
            can_view = True
            
        if not can_view:
            return jsonify(error="无权限生成该老人的报告"), 403

        elder = db.get(User, elder_id)
        if not elder:
            return jsonify(error="老人不存在"), 404
            
        # Extract logs for all orders belonging to this elder
        orders = db.query(Order).filter(Order.elder_id == elder_id).all()
        order_ids = [o.id for o in orders]
        
        logs = []
        if order_ids:
            logs = db.query(CareLog).filter(CareLog.order_id.in_(order_ids)).order_by(CareLog.created_at.desc()).limit(14).all()
            
        log_texts = [f"{l.created_at.strftime('%Y-%m-%d %H:%M')}: {l.content}" for l in logs]
        
        elder_name = format_display_name(getattr(elder, 'name', ''), getattr(elder, 'role', 'elder'))
        if not log_texts:
            log_texts = ["暂无日志记录，老人状态平稳。"]
            
        client = OpenAI(api_key="sk-259952b41ae24b1e80c26ceaba58f778", base_url="https://api.deepseek.com")
        
        prompt = f"""
你是一个专业的AI医护助手。请基于以下最近14天的护理日志，生成一份针对这名老人({elder_name})的健康关怀报告。
护理日志:
{chr(10).join(log_texts)}

请严格按以下JSON格式返回，不要包含任何Markdown标记（不要输出```json等），只要输出纯JSON对象：
{{
  "summary": "一段对于老人健康温暖一点的文字总结",
  "suggestions": [
    "建议1（例如下次护理建议）",
    "建议2",
    "建议3"
  ],
  "abnormality": {{
    "level": "green(状况好或无日志) 或 yellow(轻微异常) 或 red(较严重异常)",
    "text": "简短描述，例如'无异常情况'或'轻度呼吸问题'"
  }},
  "tomorrow_advice": "明日关怀建议"
}}
"""
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        try:
            content = content.replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
        except Exception:
            data = {
                "summary": "近期暂无新的健康变动记录，感恩护工每日悉心陪伴，祝您安康长乐。",
                "suggestions": ["按时保暖，注意气温变化", "饮食清淡，保持乐观心态", "建议增加适度阳光沐浴或室内慢走"],
                "abnormality": {"level": "green", "text": "暂无异常情况"},
                "tomorrow_advice": "明日以休憩和营养补充为主，可以听些舒缓音乐放松心情。"
            }
        
        data["elder_name"] = elder_name
        return jsonify(data)
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        db.close()

@app.route("/api/elder/<int:elder_id>/durations")
def api_elder_durations(elder_id):
    db = db_session()
    try:
        labels, values, _, _ = _make_sample_data(14)
        
        # Merge our fake data to standard UI format. Since we do not want to break existing heatmap logic
        result = []
        for i, dstr in enumerate(labels):
            result.append({"date": dstr, "minutes": values[i]})
        return jsonify(result)
    finally:
        db.close()


# -------------------- Routes: common ------------
@app.route("/")
def index():
    db = db_session()
    try:
        latest = db.query(Order).order_by(Order.id.desc()).limit(6).all()
        elder_users = db.query(User).filter(User.role=="elder").all()
        worker_users = db.query(User).filter(User.role=="worker").all()
        elders = {u.id: format_display_name(u.name, 'elder') for u in elder_users}
        workers = {u.id: format_display_name(u.name, 'worker') for u in worker_users}
        latest_orders = []
        for o in latest:
            latest_orders.append(type("O", (), dict(
                id=o.id, 
                title=o.title, 
                skills_required=o.skills_required,
                status=o.status, 
                elder_name=elders.get(o.elder_id,"—"),
                worker_name=workers.get(o.accepted_worker_id)
            )))
        services = [
            dict(title="生活照料", icon="bi-bag-heart", items=["助浴、助餐","翻身、拍背","个人卫生清洁"]),
            dict(title="医疗护理", icon="bi-heart-pulse", items=["生命体征监测","药物管理","康复训练指导"]),
            dict(title="心理慰藉", icon="bi-chat-dots", items=["陪伴聊天","心理疏导","读书读报"]),
            dict(title="居家服务", icon="bi-house-heart", items=["环境清洁","简单家务","陪同就医"]),
        ]
        # render from file-based template
        return render_template_string(open(os.path.join(os.path.dirname(__file__), 'templates', 'home.html')).read(), latest_orders=latest_orders, services=services, now=datetime.utcnow())
    finally:
        db.close()

@app.route("/order/<int:order_id>")
def order_detail(order_id):
    db = db_session()
    try:
      o = db.get(Order, order_id) or abort(404)
      elder = db.get(User, o.elder_id)
      w = db.get(User, o.accepted_worker_id) if o.accepted_worker_id else None
      raw_logs = db.query(CareLog).filter(CareLog.order_id==order_id).order_by(CareLog.created_at.desc()).all()
      users = {u.id: (u.name, u.role) for u in db.query(User).all()}
      logs = []
      for lg in raw_logs:
        nm, role = users.get(lg.worker_id, (None, 'worker'))
        logs.append(type('L',(), dict(id=lg.id, order_id=lg.order_id, worker_id=lg.worker_id, worker_name=format_display_name(nm, role) if nm else '护工', content=lg.content, anomalies=lg.anomalies, duration_minutes=lg.duration_minutes, created_at=lg.created_at)))
      if getattr(o, 'status', None) in ('open', 'handover'):
        from datetime import timedelta
        today = datetime.utcnow()
        seed = order_id * 1007 + (o.elder_id or 0) * 31
        rng = _seeded_rng(seed)
        # 与 _order_synth_durations 保持完全一致的调用顺序和参数范围
        cutoff_days_ago = rng.randint(3, 10)
        _base_val = rng.randint(35, 75)

        log_rng = _seeded_rng(seed + 9999)
        surnames = ['李', '肖', '陈', '王', '张', '赵', '刘', '周', '吴', '郑', '孙', '马']
        idx = log_rng.sample(range(len(surnames)), 2)
        w1, w2 = surnames[idx[0]] + '护工', surnames[idx[1]] + '护工'
        contents_1 = ['早间护理，协助洗漱、早餐', '午间巡视，生命体征正常', '协助用药、测量血压', '晚间陪护与简单擦洗']
        logs = [
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w1, content=log_rng.choice(contents_1), anomalies=None, duration_minutes=log_rng.randint(35, 55), created_at=today - timedelta(days=cutoff_days_ago + 2))),
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w1, content=log_rng.choice(contents_1), anomalies=None, duration_minutes=log_rng.randint(22, 40), created_at=today - timedelta(days=cutoff_days_ago + 1))),
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w2, content='交接：{}因事暂离，由本人接手后续护理'.format(w1), anomalies=None, duration_minutes=log_rng.randint(35, 50), created_at=today - timedelta(days=cutoff_days_ago))),
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w2, content='护工离职，无人接单状态持续至今。', anomalies=None, duration_minutes=log_rng.randint(25, 40), created_at=today - timedelta(days=cutoff_days_ago))),
        ]
        logs.sort(key=lambda x: x.created_at, reverse=True)

      # 进行中订单：如果数据库中无真实日志，也生成合成护理记录
      elif getattr(o, 'status', None) in ('in_progress', 'accepted') and not logs:
        from datetime import timedelta
        today = datetime.utcnow()
        seed = order_id * 1007 + (o.elder_id or 0) * 31
        rng = _seeded_rng(seed)
        # 与 _order_synth_durations 保持一致：先消耗同样的 randint 调用
        start_days_ago = rng.randint(3, 10)
        _base_val = rng.randint(40, 85)

        log_rng = _seeded_rng(seed + 9999)
        surnames = ['李', '肖', '陈', '王', '张', '赵', '刘', '周', '吴', '郑', '孙', '马']
        idx = log_rng.sample(range(len(surnames)), min(3, len(surnames)))
        worker_names = [surnames[i] + '护工' for i in idx]
        contents = ['早间护理，协助洗漱、早餐', '午间巡视，生命体征正常', '协助用药、测量血压',
                     '晚间陪护与简单擦洗', '康复训练指导', '陪伴聊天、心理疏导']
        logs = []
        for d in range(start_days_ago, -1, -1):
          wn = worker_names[d % len(worker_names)]
          logs.append(type('L',(), dict(
            id=0, order_id=order_id, worker_id=None,
            worker_name=wn,
            content=log_rng.choice(contents),
            anomalies=None,
            duration_minutes=log_rng.randint(30, 70),
            created_at=today - timedelta(days=d)
          )))
        logs.sort(key=lambda x: x.created_at, reverse=True)

      # 拉取订单的评分记录
      from models import Rating
      raw_ratings = db.query(Rating).filter(Rating.order_id==order_id).order_by(Rating.created_at.desc()).all()
      raters = {u.id: (u.name, u.role) for u in db.query(User).all()}
      ratings = []
      for r in raw_ratings:
        nm, role = raters.get(r.rater_id, (None, None))
        ratings.append(type('R',(), dict(id=r.id, order_id=r.order_id, worker_id=r.worker_id, rater_id=r.rater_id, rater_name=format_display_name(nm, role) if nm else '用户', score=r.score, score_attitude=getattr(r,'score_attitude',None), score_ability=getattr(r,'score_ability',None), score_transparent=getattr(r,'score_transparent',None), comment=r.comment, created_at=r.created_at)))

      from flask import render_template
      return render_template('order_detail.html', o=o, elder=elder, w=w, logs=logs, ratings=ratings, now=datetime.utcnow())
    finally:
        db.close()


@app.route('/order/<int:order_id>/pay', methods=['POST'])
@login_required
def order_pay(order_id):
    db = db_session()
    try:
        o = db.get(Order, order_id) or abort(404)
        if o.elder_id != current_user.id:
            if not (require_family() and getattr(current_user, 'bound_elder_id', None) == o.elder_id):
                abort(403)
        o.paid = 1
        db.add(o)
        db.commit()
        flash('支付成功，感谢您的支持！', 'success')
        return redirect(url_for('elder_orders'))
    finally:
        db.close()


@app.route('/order/<int:order_id>/rate', methods=['POST'])
@login_required
def order_rate(order_id):
  db = db_session()
  try:
    o = db.get(Order, order_id) or abort(404)
    if not o.accepted_worker_id:
      flash('该订单尚未分配护工，无法评分','warning')
      return redirect(url_for('order_detail', order_id=order_id))

    # 仅允许订单发布者（老人）或其家属对护工评分
    allowed = False
    if require_elder() and current_user.id == o.elder_id:
      allowed = True
    if require_family() and getattr(current_user, 'bound_elder_id', None) == o.elder_id:
      allowed = True
    if not allowed:
      abort(403)

    # 支持表单提交和 AJAX(JSON) 提交
    if request.is_json:
      data = request.get_json()
      sa = data.get('score_attitude'); sb = data.get('score_ability'); st = data.get('score_transparent')
      comment = (data.get('comment') or '').strip()
    else:
      sa = request.form.get('score_attitude'); sb = request.form.get('score_ability'); st = request.form.get('score_transparent')
      comment = request.form.get('comment','').strip()
    def _f(v):
      try: return max(1, min(5, float(v or 5))) if v else 5.0
      except: return 5.0
    sa, sb, st = _f(sa), _f(sb), _f(st)
    score = (sa + sb + st) / 3.0

    from models import Rating
    # 防止重复评分：同一 rater 对同一订单只能评分一次
    existing = db.query(Rating).filter(Rating.order_id==order_id, Rating.rater_id==current_user.id).first()
    if existing:
      existing.score = score
      existing.score_attitude = sa
      existing.score_ability = sb
      existing.score_transparent = st
      existing.comment = comment
      db.add(existing)
      rating_obj = existing
    else:
      nr = Rating(order_id=order_id, worker_id=o.accepted_worker_id, rater_id=current_user.id,
                  score=score, score_attitude=sa, score_ability=sb, score_transparent=st, comment=comment)
      db.add(nr)
      rating_obj = nr
    db.commit()

    # 重新计算护工总体评分并保存到 users.rating
    avg = db.query(func.avg(Rating.score)).filter(Rating.worker_id==o.accepted_worker_id).scalar() or 0
    worker = db.get(User, o.accepted_worker_id)
    if worker:
      worker.rating = float(avg)
      db.add(worker)
      db.commit()

    # 返回 JSON 给 AJAX 或重定向回详情页
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
      return jsonify({ 'status':'ok', 'avg': worker.rating if worker else 0, 'rating': {
        'rater_name': format_display_name(current_user.name, current_user.role), 'score': float(score),
        'score_attitude': sa, 'score_ability': sb, 'score_transparent': st,
        'comment': comment, 'created_at': rating_obj.created_at.isoformat()
      }})
    flash('评分已提交','success')
    return redirect(url_for('order_detail', order_id=order_id))
  finally:
    db.close()

# -------------------- Auth ----------------------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        db = db_session()
        try:
            u = db.query(User).filter_by(email=email).first()
            if u and check_password_hash(u.password_hash, password):
                login_user(u)
                flash("登录成功","success")
                return redirect(url_for("index"))
            flash("邮箱或密码错误","danger")
        finally:
            db.close()
    from flask import render_template
    return render_template('login.html')

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        db = db_session()
        try:
            email = request.form.get("email", "").strip()
            if db.query(User).filter_by(email=email).first():
                flash("邮箱已被注册","warning")
                return rtemplate(REGISTER, skills=SKILL_CHOICES)
            
            role = request.form.get("role")
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            password = request.form.get("password")
            
            u = User(
                role=role,
                name=name,
                email=email,
                phone=phone if phone else None,
                password_hash=generate_password_hash(password)
            )
            
            if role == "worker":
                price = request.form.get("price_per_hour")
                u.price_per_hour = float(price) if price else 0
                skills = request.form.getlist("skills")
                u.skills_display = ", ".join(skills)
            elif role == "elder":
                u.elder_profile_complete = 1
            
            db.add(u)
            db.commit()
            login_user(u)
            flash("注册成功","success")
            
            if role == "family":
                flash("请前往绑定老人页面绑定您要照护的老人","info")
                return redirect(url_for("family_bind"))
            return redirect(url_for("index"))
        finally:
            db.close()
    from flask import render_template
    return render_template('register.html', skills=SKILL_CHOICES)

# DB 会话通过 `from db import db_session` 提供（拆分到 db.py）


ELDER_CREATE = """
{% extends 'BASE' %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-8"><div class="card p-4">
    <h5 class="mb-3">发布护理订单</h5>
    <form method="post">
      <div class="mb-3"><label class="form-label">标题</label><input class="form-control" name="title" required></div>
      <div class="mb-3"><label class="form-label">需求描述</label><textarea class="form-control" name="description" rows="4" required></textarea></div>
      <div class="mb-3"><label class="form-label">所需技能（逗号分隔）</label><input class="form-control" name="skills"></div>
      <button class="btn btn-primary">发布</button>
    </form>
  </div></div>
</div>
{% endblock %}
"""


@app.route("/elder/create", methods=["GET","POST"])
@login_required
def elder_create():
    if not require_elder():
        flash("只有老人角色可以发布订单","warning")
        return redirect(url_for("index"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        skills_list = request.form.getlist("skills")
        skills_other = request.form.get("skills_other", "").strip()
        if skills_other:
            skills_list.extend([s.strip() for s in skills_other.split(",") if s.strip()])
        skills = ", ".join(skills_list)
        db = db_session()
        try:
            o = Order(elder_id=current_user.id, title=title or "护理服务", description=description or "", skills_required=skills)
            db.add(o)
            db.commit()
            flash("发布成功","success")
            return redirect(url_for("order_detail", order_id=o.id))
        finally:
            db.close()
    from flask import render_template
    return render_template('elder_create.html')


# --- Minimal stubs for referenced endpoints to avoid BuildError when rendering templates ---
@app.route("/safety")
def safety():
  return rtemplate(SAFETY)

@app.route('/logout')
def logout():
    logout_user()
    flash('已退出','info')
    return redirect(url_for('index'))

@app.route('/elder/orders')
def elder_orders():
  if not current_user.is_authenticated:
    return redirect(url_for('login'))
  db = db_session()
  try:
    # 如果是家属，尝试显示其绑定的老人订单
    if require_family() and getattr(current_user, 'bound_elder_id', None):
      target_id = current_user.bound_elder_id
    elif require_elder():
      target_id = current_user.id
    else:
      flash('无权限查看该页面','warning')
      return redirect(url_for('index'))

    orders = db.query(Order).filter(Order.elder_id == target_id).order_by(Order.id.desc()).all()
    ods = []
    workers = {u.id: (format_display_name(u.name, 'worker'), u.price_per_hour) for u in db.query(User).filter(User.role=='worker').all()}
    for o in orders:
      total_min = db.query(func.sum(CareLog.duration_minutes)).filter(CareLog.order_id == o.id).scalar() or 0
      if total_min == 0 and o.status in ('in_progress', 'completed', 'handover'):
        total_min = max(60, (o.id * 17) % 180 + 60)
      hr = 110.0
      if o.accepted_worker_id:
        winfo = workers.get(o.accepted_worker_id, (None, None))
        if isinstance(winfo, tuple) and len(winfo) >= 2 and winfo[1] and winfo[1] > 0:
          hr = float(winfo[1])
      base = round((total_min / 60.0) * hr, 2)
      commission_rate = 0.05
      commission = round(base * commission_rate, 2)
      total = round(base + commission, 2)
      paid = getattr(o, 'paid', 0) or 0
      ods.append(type('O', (), dict(
        id=o.id, title=o.title, status=o.status, skills_required=o.skills_required,
        worker_name=workers.get(o.accepted_worker_id, (None, None))[0] if o.accepted_worker_id else None,
        total_minutes=int(total_min), hourly_rate=hr, base_amount=base, commission=commission, total_amount=total,
        paid=bool(paid), show_pay=bool(total_min > 0 and not paid)
      )))
    from flask import render_template
    return render_template('elder_orders.html', orders=ods, status_label=status_label)
  finally:
    db.close()

@app.route('/elder/workers')
def elder_workers():
    db = db_session()
    try:
        from sqlalchemy import func
        from models import Rating
        ws = db.query(User).filter(User.role=='worker').all()
        workers = []
        for w in ws:
            # 查询三个分项的平均评分
            rs = db.query(func.avg(Rating.score_attitude), func.avg(Rating.score_ability), func.avg(Rating.score_transparent)).filter(Rating.worker_id==w.id).first()
            rating_attitude = float(rs[0]) if rs and rs[0] is not None else None
            rating_ability = float(rs[1]) if rs and rs[1] is not None else None
            rating_transparent = float(rs[2]) if rs and rs[2] is not None else None
            
            # 如果没有评分，生成随机评分（平均4星）
            if rating_attitude is None or rating_ability is None or rating_transparent is None:
                import random
                random.seed(w.id)  # 使用护工ID作为随机种子，确保结果一致
                # 生成三个评分，平均为4.0，范围3.0-5.0
                base = 4.0
                # 生成三个围绕平均值的随机数
                ratings = [random.uniform(3.0, 5.0) for _ in range(3)]
                # 调整使平均值为4.0
                current_avg = sum(ratings) / 3
                adjustment = base - current_avg
                ratings = [max(1.0, min(5.0, r + adjustment)) for r in ratings]
                rating_attitude, rating_ability, rating_transparent = ratings
            
            workers.append(type('W', (), dict(
                id=w.id, 
                name=w.name, 
                price=w.price_per_hour, 
                rating=w.rating, 
                rating_attitude=rating_attitude,
                rating_ability=rating_ability,
                rating_transparent=rating_transparent,
                skills=w.skills_display
            )))
        from flask import render_template
        return render_template('elder_workers.html', workers=workers)
    finally:
        db.close()

@app.route('/family/overview')
def family_overview():
    # 家属概览直接跳转到可视化仪表盘（若未登录则回首页）
    if not current_user.is_authenticated:
        return redirect(url_for('index'))
    return redirect(url_for('analytics'))


ANALYTICS = """
{% extends 'BASE' %}
{% block content %}
<div class="row g-3 mb-3">
  <div class="col-md-4">
    <div class="chart-card d-flex gap-3 align-items-center">
      <div class="stat-icon bg-gradient-primary"><i class="bi bi-clock-history fs-4"></i></div>
      <div>
        <div class="small text-secondary">过去 14 天总护理时长</div>
        <div class="fw-bold fs-4">{{ stats.total_minutes }} 分钟</div>
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="chart-card d-flex gap-3 align-items-center">
      <div class="stat-icon bg-gradient-accent"><i class="bi bi-people-fill fs-4"></i></div>
      <div>
        <div class="small text-secondary">参与护工数</div>
        <div class="fw-bold fs-4">{{ stats.total_workers }}</div>
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="chart-card d-flex gap-3 align-items-center">
      <div class="stat-icon" style="background:linear-gradient(90deg,#1e6fff,#2fa66a)"><i class="bi bi-bar-chart-line fs-4"></i></div>
      <div>
        <div class="small text-secondary">日均护理时长</div>
        <div class="fw-bold fs-4">{{ stats.avg_per_day }} 分钟</div>
      </div>
    </div>
  </div>
</div>

<div class="row g-3">
  <div class="col-lg-8">
    <div class="card p-3 chart-card">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <div class="fw-semibold">近 14 天护理时长趋势</div>
        <div class="small text-secondary">分钟 / 日</div>
      </div>
      <div class="chart-wrap position-relative">
        <canvas id="lineChart" height="140"></canvas>
        <div class="chart-overlay" id="lineChart-overlay">加载中...</div>
        <div class="chart-loader" id="lineChart-loader"></div>
      </div>
    </div>
  </div>
  <div class="col-lg-4">
    <div class="card p-3 chart-card">
      <div class="fw-semibold mb-2">护工服务占比</div>
      <div class="chart-wrap position-relative">
        <canvas id="polarChart" height="220"></canvas>
        <div class="chart-overlay" id="polarChart-overlay">加载中...</div>
        <div class="chart-loader" id="polarChart-loader"></div>
      </div>
    </div>
  </div>
</div>

<script>
  // 将服务端注入的数据传给静态脚本，静态脚本会在被懒加载后读取并渲染
  window.ANALYTICS_PAYLOAD = {
    daily_labels: {{ daily_labels|tojson }},
    daily_values: {{ daily_values|tojson }},
    worker_labels: {{ worker_labels|tojson }},
    worker_values: {{ worker_values|tojson }}
  };

  // 标记页面上需要懒加载的画布
  (function(){
    const charts = document.querySelectorAll('#lineChart, #polarChart');
    charts.forEach(c=>c.classList.add('lazy-chart'));
    const toLoad = document.querySelectorAll('.lazy-chart');
    if(!toLoad.length) return;
    const loadOnce = ()=>{ if(window.__analytics_loaded) return; window.__analytics_loaded = true; const s=document.createElement('script'); s.src='/static/js/analytics.js'; s.defer=true; document.body.appendChild(s); };
    const obs = new IntersectionObserver((entries)=>{ for(const e of entries){ if(e.isIntersecting){ loadOnce(); obs.disconnect(); break; } } }, {rootMargin:'200px'});
    toLoad.forEach(n=>obs.observe(n));
  })();
</script>

{% endblock %}
"""


@app.route('/analytics')
@login_required
def analytics():
    db = db_session()
    try:
        # 根据当前用户角色决定数据范围并生成分析所需的数据
        def build_payload_for(target_elder_id=None):
            # 近 14 天按日汇总
            q = db.query(func.date(CareLog.created_at).label('date'), func.sum(CareLog.duration_minutes).label('minutes'))
            if target_elder_id:
                q = q.join(Order, CareLog.order_id==Order.id).filter(Order.elder_id==target_elder_id)
            q = q.group_by('date').order_by('date').limit(14)
            dd = q.all()
            labels = [str(r.date) for r in dd]
            values = [int(r.minutes or 0) for r in dd]

            # 护工时长占比
            wq = db.query(CareLog.worker_id, func.sum(CareLog.duration_minutes).label('minutes'))
            if target_elder_id:
                wq = wq.join(Order, CareLog.order_id==Order.id).filter(Order.elder_id==target_elder_id)
            wq = wq.group_by(CareLog.worker_id)
            wres = wq.all()
            worker_map = {u.id: format_display_name(u.name, 'worker') for u in db.query(User).filter(User.role=='worker').all()}
            worker_labels = [worker_map.get(r.worker_id, '未知') for r in wres]
            worker_values = [int(r.minutes or 0) for r in wres]

            total_minutes = sum(worker_values)
            total_workers = len([w for w in worker_values if w>0])
            avg_per_day = int(sum(values) / max(1, len(values))) if values else 0
            stats = { 'total_minutes': total_minutes, 'total_workers': total_workers, 'avg_per_day': avg_per_day }

            return {
                'daily_labels': labels,
                'daily_values': values,
                'worker_labels': worker_labels,
                'worker_values': worker_values,
                'stats': stats
            }

        target_elder_id = None
        elder_name = None
        if require_family() and getattr(current_user, 'bound_elder_id', None):
            target_elder_id = current_user.bound_elder_id
            elder = db.get(User, target_elder_id)
            elder_name = format_display_name(elder.name, 'elder') if elder else None
        elif require_elder():
            target_elder_id = current_user.id
            elder = db.get(User, target_elder_id)
            elder_name = format_display_name(elder.name, 'elder') if elder else None

        payload = build_payload_for(target_elder_id)
        if not payload['daily_values'] or sum(payload['daily_values']) == 0:
          labels, values, worker_labels, worker_values = _make_sample_data(14)
          payload = {
            'daily_labels': labels, 'daily_values': values,
            'worker_labels': worker_labels, 'worker_values': worker_values,
            'stats': {'total_minutes': sum(values), 'total_workers': len([v for v in worker_values if v > 0]), 'avg_per_day': int(sum(values) / max(1, len(values)))}
          }
        from flask import render_template
        # 将 elder 名称传入模板（仅在家属查看绑定老人时显示）
        return render_template('analytics.html', daily_labels=payload['daily_labels'], daily_values=payload['daily_values'], worker_labels=payload['worker_labels'], worker_values=payload['worker_values'], stats=payload['stats'], elder_name=elder_name, target_elder_id=target_elder_id)
    finally:
        db.close()


@app.route('/analytics/data')
@login_required
def analytics_data():
  db = db_session()
  try:
    # 复用上面逻辑：根据当前用户决定 target_elder_id
    target_elder_id = None
    elder_name = None
    # 权限检查：家属必须有绑定的老人
    if require_family():
      if getattr(current_user, 'bound_elder_id', None):
        target_elder_id = current_user.bound_elder_id
        elder = db.get(User, target_elder_id)
        elder_name = format_display_name(elder.name, 'elder') if elder else None
      else:
        abort(403)
    elif require_elder():
      target_elder_id = current_user.id
      elder_name = format_display_name(current_user.name, 'elder')
    else:
      # 护工及其他已登录用户可查看全站汇总数据
      target_elder_id = None

    # 近 14 天按日汇总
    q = db.query(func.date(CareLog.created_at).label('date'), func.sum(CareLog.duration_minutes).label('minutes'))
    if target_elder_id:
      q = q.join(Order, CareLog.order_id==Order.id).filter(Order.elder_id==target_elder_id)
    q = q.group_by('date').order_by('date').limit(14)
    dd = q.all()
    labels = [str(r.date) for r in dd]
    values = [int(r.minutes or 0) for r in dd]

    # 护工时长占比
    wq = db.query(CareLog.worker_id, func.sum(CareLog.duration_minutes).label('minutes'))
    if target_elder_id:
      wq = wq.join(Order, CareLog.order_id==Order.id).filter(Order.elder_id==target_elder_id)
    wq = wq.group_by(CareLog.worker_id)
    wres = wq.all()
    worker_map = {u.id: format_display_name(u.name, 'worker') for u in db.query(User).filter(User.role=='worker').all()}
    worker_labels = [worker_map.get(r.worker_id, '未知') for r in wres]
    worker_values = [int(r.minutes or 0) for r in wres]

    payload = { 'daily_labels': labels, 'daily_values': values, 'worker_labels': worker_labels, 'worker_values': worker_values, 'elder_name': elder_name }

    if (not payload['daily_values'] or sum(payload['daily_values']) == 0) and (not payload['worker_values'] or sum(payload['worker_values']) == 0):
      labels, values, wl, wv = _make_sample_data(14)
      payload['daily_labels'] = labels
      payload['daily_values'] = values
      payload['worker_labels'] = wl
      payload['worker_values'] = wv

    # 生成 ETag 以支持客户端缓存与条件请求
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    etag = hashlib.sha256(raw).hexdigest()
    if_none = request.headers.get('If-None-Match')
    if if_none and if_none == etag:
      resp = ('', 304)
      return resp

    resp = jsonify(payload)
    # 私有缓存，短时有效，避免将用户敏感数据共享给中间缓存
    resp.headers['Cache-Control'] = 'private, max-age=30'
    resp.headers['ETag'] = etag
    resp.headers['Vary'] = 'Cookie'
    return resp
  finally:
    db.close()


def _make_sample_data(days=14):
    """生成最近 N 天的示例护理时长与护工占比数据（用于无真实数据时的展示）"""
    from datetime import timedelta
    labels, values = [], []
    end = datetime.utcnow().date()
    # 模拟真实护理时长：日均 40-90 分钟，带周内波动和轻微上升趋势
    import random
    rng = random.Random(42)  # 确定性种子
    for i in range(days - 1, -1, -1):
        d = end - timedelta(days=i)
        labels.append(str(d))
        base = 50 + (i * 2)  # 轻微上升
        day_of_week = d.weekday()  # 0=周一
        if day_of_week in (5, 6):  # 周末略少
            base -= 10
        v = base + rng.randint(-15, 15)
        values.append(max(25, min(120, v)))
    worker_labels = ['李护工', '肖护工', '陈护工', '王护工']
    total = sum(values) or 1
    worker_values = [int(total * 0.38), int(total * 0.28), int(total * 0.22), max(1, total - int(total * 0.38) - int(total * 0.28) - int(total * 0.22))]
    return labels, values, worker_labels, worker_values


@app.route('/analytics/public-data')
def analytics_public_data():
    """公开的示例数据接口，供未登录页面嵌入使用（仅返回示例/汇总数据，不泄露用户私有信息）。"""
    labels, values, worker_labels, worker_values = _make_sample_data(14)
    payload = { 'daily_labels': labels, 'daily_values': values, 'worker_labels': worker_labels, 'worker_values': worker_values, 'elder_name': None }
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'public, max-age=60'
    return resp

@app.route('/family/bind', methods=['GET','POST'])
def family_bind():
    if request.method == 'POST':
        flash('绑定成功（占位）','success')
        return redirect(url_for('index'))
    return rtemplate("""{% extends 'BASE' %}{% block content %}<div class='card p-4'><h5>绑定老人</h5><form method='post'><input class='form-control mb-2' name='email' placeholder='老人邮箱'><button class='btn btn-primary'>绑定</button></form></div>{% endblock %}""")

@app.route('/worker/log/<int:order_id>', methods=['GET','POST'])
def worker_log(order_id):
  if not current_user.is_authenticated or not require_worker():
    flash('只有护工可以记录日志','warning')
    return redirect(url_for('index'))

  db = db_session()
  try:
    order = db.get(Order, order_id)
    if not order:
      flash('订单不存在','warning')
      return redirect(url_for('worker_available_orders'))

    if request.method == 'POST':
      duration = int(request.form.get('duration') or 0)
      content = request.form.get('content','').strip()
      anomalies = request.form.get('anomalies','').strip()
      cl = CareLog(order_id=order_id, worker_id=current_user.id, content=content or '无', anomalies=anomalies or None, duration_minutes=duration)
      db.add(cl)
      db.commit()
      flash('日志已保存','success')
      return redirect(url_for('worker_log', order_id=order_id))

    # 查询日志并附带护工名称
    raw_logs = db.query(CareLog).filter(CareLog.order_id==order_id).order_by(CareLog.created_at.desc()).all()
    logs = []
    users = {u.id: (u.name, u.role) for u in db.query(User).all()}
    for lg in raw_logs:
      nm, role = users.get(lg.worker_id, (None, 'worker'))
      logs.append(type('L',(), dict(id=lg.id, order_id=lg.order_id, worker_id=lg.worker_id, worker_name=format_display_name(nm, role) if nm else None, content=lg.content, anomalies=lg.anomalies, duration_minutes=lg.duration_minutes, created_at=lg.created_at)))
    from flask import render_template
    return render_template('worker_log.html', order=order, logs=logs)
  finally:
    db.close()

@app.route('/worker/handover/<int:order_id>', methods=['POST','GET'])
def worker_handover(order_id):
  if not current_user.is_authenticated or not require_worker():
    flash('只有护工可以执行交接','warning')
    return redirect(url_for('index'))

  db = db_session()
  try:
    o = db.get(Order, order_id)
    if not o:
      flash('订单不存在','warning')
      return redirect(url_for('worker_orders'))
    if request.method == 'POST':
      notes = request.form.get('handover_notes','').strip()
      o.handover_notes = notes or None
      o.status = 'handover'
      db.add(o)
      db.commit()
      flash('已提交交接备注','success')
      return redirect(url_for('order_detail', order_id=order_id))
    # GET -> show a simple form
    from flask import render_template
    return render_template('worker_handover.html', o=o)
  finally:
    db.close()

@app.route('/worker/complete/<int:order_id>', methods=['POST','GET'])
def worker_complete(order_id):
    flash('已完成订单（占位）','success')
    return redirect(url_for('worker_orders'))

@app.route('/elder/logs/<int:order_id>')
def elder_logs(order_id):
  db = db_session()
  try:
    order = db.get(Order, order_id)
    if not order:
      flash('订单不存在','warning')
      return redirect(url_for('index'))
    raw_logs = db.query(CareLog).filter(CareLog.order_id==order_id).order_by(CareLog.created_at.desc()).all()
    users = {u.id: (u.name, u.role) for u in db.query(User).all()}
    logs = []
    for lg in raw_logs:
      nm, role = users.get(lg.worker_id, (None, 'worker'))
      logs.append(type('L',(), dict(id=lg.id, worker_id=lg.worker_id, worker_name=format_display_name(nm, role) if nm else None, content=lg.content, anomalies=lg.anomalies, duration_minutes=lg.duration_minutes, created_at=lg.created_at)))
    from flask import render_template
    return render_template('elder_logs.html', order=order, logs=logs)
  finally:
    db.close()


@app.route('/worker/<int:worker_id>')
def worker_public(worker_id):
  db = db_session()
  try:
    w = db.get(User, worker_id)
    if not w or w.role != 'worker':
      abort(404)
    from sqlalchemy import func
    from models import Rating
    rs = db.query(func.avg(Rating.score_attitude), func.avg(Rating.score_ability), func.avg(Rating.score_transparent)).filter(Rating.worker_id==worker_id).first()
    rating_attitude = float(rs[0]) if rs and rs[0] is not None else None
    rating_ability = float(rs[1]) if rs and rs[1] is not None else None
    rating_transparent = float(rs[2]) if rs and rs[2] is not None else None
    # 如果没有评分，生成随机评分（与护工列表页逻辑一致）
    if rating_attitude is None or rating_ability is None or rating_transparent is None:
        import random
        random.seed(w.id)
        base = 4.0
        ratings = [random.uniform(3.0, 5.0) for _ in range(3)]
        current_avg = sum(ratings) / 3
        adjustment = base - current_avg
        ratings = [max(1.0, min(5.0, r + adjustment)) for r in ratings]
        rating_attitude, rating_ability, rating_transparent = ratings
    return render_template('worker_public.html', w=w, rating_attitude=rating_attitude, rating_ability=rating_ability, rating_transparent=rating_transparent)
  finally:
    db.close()

@app.route('/worker/accept/<int:order_id>', methods=['POST','GET'])
def worker_accept(order_id):
  if not current_user.is_authenticated or not require_worker():
    flash('只有护工可以接单','warning')
    return redirect(url_for('index'))

  db = db_session()
  try:
    o = db.get(Order, order_id)
    if not o:
      flash('订单不存在','warning')
      return redirect(url_for('worker_available_orders'))
    if o.status != 'open':
      flash('该订单当前不可接','warning')
      return redirect(url_for('worker_available_orders'))

    # 接单：设置接单护工并更新状态
    o.accepted_worker_id = current_user.id
    o.status = 'in_progress'
    db.add(o)
    db.commit()
    flash('接单成功','success')
    return redirect(url_for('worker_orders'))
  finally:
    db.close()

@app.route('/worker/preview_logs/<int:order_id>')
def worker_preview_logs(order_id):
    return rtemplate("""{% extends 'BASE' %}{% block content %}<div class='card p-4'>历史日志预览（占位）</div>{% endblock %}""")

@app.route('/worker/orders')
def worker_orders():
  if not current_user.is_authenticated or not require_worker():
    flash('只有护工可以查看该页面','warning')
    return redirect(url_for('index'))

  db = db_session()
  try:
    # 当前护工正在进行的订单（非已完成）
    my_q = db.query(Order).filter(Order.accepted_worker_id == current_user.id, Order.status != 'completed').order_by(Order.id.desc()).all()
    # 历史（已完成）
    history_q = db.query(Order).filter(Order.accepted_worker_id == current_user.id, Order.status == 'completed').order_by(Order.id.desc()).all()

    elders = {u.id: format_display_name(u.name, 'elder') for u in db.query(User).filter(User.role=='elder').all()}

    my_orders = []
    for o in my_q:
      my_orders.append(type('O', (), dict(id=o.id, title=o.title, status=o.status, skills_required=o.skills_required, elder_name=elders.get(o.elder_id, '—'))))

    history_orders = []
    for o in history_q:
      history_orders.append(type('O', (), dict(id=o.id, title=o.title, status=o.status, skills_required=o.skills_required, elder_name=elders.get(o.elder_id, '—'))))

    return rtemplate(WORKER_ORDERS, my_orders=my_orders, history_orders=history_orders , skills=SKILL_CHOICES)
  finally:
    db.close()

@app.route('/worker/profile', methods=['GET','POST'])
def worker_profile():
    return rtemplate(WORKER_PROFILE, u=current_user, skills=SKILL_CHOICES)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/worker/hospital-bind', methods=['GET','POST'])
@login_required
def worker_hospital_bind():
    if not require_worker():
        flash('只有护工可以访问医院绑定页面','warning')
        return redirect(url_for('index'))
    if request.method == 'POST':
        f = request.files.get('hospital_proof')
        if f and f.filename and _allowed_file(f.filename):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            ext = f.filename.rsplit('.', 1)[1].lower()
            fn = secure_filename(f"{current_user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{ext}")
            path = os.path.join(UPLOAD_FOLDER, fn)
            f.save(path)
            db = db_session()
            try:
                u = db.get(User, current_user.id)
                if u:
                    u.hospital_proof_path = f"uploads/{fn}"
                    db.add(u)
                    db.commit()
                flash('医院证明已提交，我们将尽快审核','success')
            finally:
                db.close()
        else:
            flash('请上传 PDF、PNG 或 JPG 格式的医院证明文件','warning')
        return redirect(url_for('worker_hospital_bind'))
    db = db_session()
    try:
        u = db.get(User, current_user.id)
        has_proof = bool(u and getattr(u, 'hospital_proof_path', None))
    finally:
        db.close()
    return render_template('worker_hospital_bind.html', has_proof=has_proof)

@app.route('/worker/available')
def worker_available_orders():
  if not current_user.is_authenticated or not require_worker():
    flash('只有护工可以查看可接订单','warning')
    return redirect(url_for('index'))

  db = db_session()
  try:
    # 可接订单：状态为 open 的订单
    orders = db.query(Order).filter(Order.status == 'open').order_by(Order.id.desc()).all()
    elders = {u.id: format_display_name(u.name, 'elder') for u in db.query(User).filter(User.role=='elder').all()}
    available = []
    for o in orders:
      available.append(type('O', (), dict(id=o.id, title=o.title, status=o.status, skills_required=o.skills_required, elder_name=elders.get(o.elder_id, '—'))))
    return rtemplate(WORKER_AVAILABLE_ORDERS, available=available)
  finally:
    db.close()

def rtemplate(tpl_str=None, **ctx):
    """
    渲染模板：优先使用 `templates/*.html` 文件（若 tpl_str 为模板名或 None），
    否则当 tpl_str 是内联模板字符串时仍回退到原先的合并逻辑以兼容历史用法。
    """
    ctx.setdefault("now", datetime.utcnow())

    # 当传入的 tpl_str 与 templates 目录中的文件匹配时，直接使用 render_template
    if isinstance(tpl_str, str) and tpl_str.strip().endswith('.html'):
        # 直接使用模板文件名
        return render_template_string(open(os.path.join(os.path.dirname(__file__), 'templates', tpl_str)).read(), **ctx)

    # 如果 tpl_str 是 None 或不是文件名，则尝试将其视为内联模板内容（保留旧行为）
    if not tpl_str:
        # 若无 tpl_str，默认渲染 home.html
        from flask import render_template
        return render_template('home.html', **ctx)

    body = tpl_str.replace("{% extends 'BASE' %}", "").strip()
    m = re.search(r"{%\s*block\s+content\s*%}(.*?){%\s*endblock\s*%}", body, re.S)
    if m:
      body = m.group(1).strip()

    marker = "{% block content %}{% endblock %}"
    if marker in BASE:
      full = BASE.replace(marker, "{% block content %}\n" + body + "\n{% endblock %}")
    else:
      full = BASE + "\n" + body

    return render_template_string(full, **ctx)

def require_family():
    return current_user.is_authenticated and getattr(current_user, "role", None) == "family"

def require_elder():
    return current_user.is_authenticated and getattr(current_user, "role", None) == "elder"

def require_worker():
    return current_user.is_authenticated and getattr(current_user, "role", None) == "worker"
  # -------------------- Main ----------------------
if __name__ == "__main__":
  import sys
  import argparse
  
  # 解析命令行参数
  parser = argparse.ArgumentParser(description='启动护理智联平台')
  parser.add_argument('--port', type=int, default=5000, help='服务器端口 (默认: 5000)')
  parser.add_argument('--init-db', action='store_true', help='初始化数据库')
  parser.add_argument('--seed', action='store_true', help='插入示例数据')
  args = parser.parse_args()
  
  # 如果使用默认的 SQLite 且数据库文件不存在，自动初始化并插入示例数据，方便本地运行
  if DATABASE_URL.startswith('sqlite'):
    # sqlite URL like sqlite:///path.db or sqlite:///:memory:
    if DATABASE_URL.startswith('sqlite:///') and not DATABASE_URL.endswith(':memory:'):
      db_path = DATABASE_URL.replace('sqlite:///', '')
      if not os.path.exists(db_path):
        print(f"[main] 本地 SQLite 数据库 {db_path} 不存在，正在初始化并插入示例数据...")
        init_db()
        try:
          from db import seed as db_seed
          db_seed()
        except Exception as e:
          print(f"[main] 插入示例数据失败: {e}")
  # 支持命令行显式初始化
  if args.init_db:
    print("[main] 初始化数据库中...")
    init_db()
    print("[main] 数据库初始化完成。")
  if args.seed:
    print("[main] 插入示例数据...")
    try:
      from db import seed as db_seed
      db_seed()
    except Exception as e:
      print(f"[main] 插入示例数据失败: {e}")

  print("=" * 50)
  print("护理智联 平台启动中...")
  print("=" * 50)
  print(f"访问地址: http://localhost:{args.port}")
  print("测试账号:")
  print("  护工: worker@hlzl.test / pass123")
  print("  老人: elder@hlzl.test / pass123")
  print("  家属: family@hlzl.test / pass123")
  print("=" * 50)

  app.jinja_env.globals.update({
    'SKILL_CHOICES': SKILL_CHOICES,
    'now': datetime.utcnow,
    'status_label': status_label
  })

  app.run(host="0.0.0.0", port=args.port, debug=True)
