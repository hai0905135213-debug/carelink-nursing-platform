import os
from datetime import datetime
import re
from collections import defaultdict

from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# 本模块拆分：配置、DB、模型、表单
from config import SECRET_KEY, status_label, now, DATABASE_URL
from db import db_session, init_db
from models import User, Order, CareLog
from forms import SKILL_CHOICES
from sqlalchemy import func

# -------------------- App/Ext -------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY
login_manager = LoginManager(app)
login_manager.login_view = "login"

# 注册全局 Jinja 变量，确保在被 import 时也可用（避免仅在 __main__ 分支注册）
app.jinja_env.globals.update({
  'SKILL_CHOICES': SKILL_CHOICES,
  'now': datetime.utcnow,
  'status_label': status_label,
})

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
          <span class="me-3 align-self-center">{{ current_user.name }}（{{ {'worker':'护工','elder':'老人','family':'家属'}[current_user.role] }}）</span>
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
      {% for box in services %}
      <div class="col-md-6"><div class="card p-3">
        <div class="d-flex align-items-center mb-2">
          <span class="badge badge-soft me-2"><i class="bi {{ box.icon }}"></i></span>
          <div class="fw-semibold">{{ box.title }}</div>
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
  <div class="text-secondary small">发布者：{{ elder.name }}</div>
  <div class="text-secondary small">需求：{{ o.skills_required or '—' }}</div>
  <div class="mt-2">{{ o.description }}</div>
  <div class="mt-3">
    <span class="status-badge status-{{ o.status }}">{{ {'open':'待接单','in_progress':'进行中','completed':'已完成','handover':'待接手'}[o.status] }}</span>
  {% if w %}<span class="badge rounded-pill text-bg-primary ms-2">护工：{{ w.name }}</span>{% endif %}
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
        <li>2026-02-10 10:00：护工 A 完成早间护理</li>
        <li>2026-02-11 18:20：护工 B 交接并补充用药记录</li>
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

# -------------------- API -----------------------
@app.route("/api/order/<int:order_id>/durations")
@login_required
def api_order_durations(order_id):
    db = db_session()
    try:
        # 确保请求者是订单相关人员
        o = db.get(Order, order_id)
        if not o or (o.elder_id != current_user.id and o.accepted_worker_id != current_user.id):
            return jsonify(error="无权限访问该订单"), 403
        
        # 查询该订单的所有护理记录，按日期分组
        data = db.query(
            func.date(CareLog.created_at).label("date"),
            func.sum(CareLog.duration_minutes).label("minutes")
        ).filter(CareLog.order_id == order_id).group_by("date").all()
        
        # 处理结果
        result = [{"date": str(d.date), "minutes": d.minutes} for d in data]
        return jsonify(result)
    finally:
        db.close()

@app.route("/api/order/<int:order_id>/worker-shares")
@login_required
def api_order_worker_shares(order_id):
    db = db_session()
    try:
        # 确保请求者是订单相关人员
        o = db.get(Order, order_id)
        if not o or (o.elder_id != current_user.id and o.accepted_worker_id != current_user.id):
            return jsonify(error="无权限访问该订单"), 403
        
        # 查询该订单的护理记录，统计每位护工的服务时长
        data = db.query(
            CareLog.worker_id,
            func.sum(CareLog.duration_minutes).label("minutes")
        ).filter(CareLog.order_id == order_id).group_by(CareLog.worker_id).all()
        
        workers = {u.id: u.name for u in db.query(User).filter(User.role == "worker").all()}
        
        # 处理结果
        result = [{"worker": workers.get(d.worker_id), "minutes": d.minutes} for d in data]
        return jsonify(result)
    finally:
        db.close()

# -------------------- Routes: common ------------
@app.route("/")
def index():
    db = db_session()
    try:
        latest = db.query(Order).order_by(Order.id.desc()).limit(6).all()
        elders = {u.id: u.name for u in db.query(User).filter(User.role=="elder").all()}
        workers = {u.id: u.name for u in db.query(User).filter(User.role=="worker").all()}
        latest_orders = []
        for o in latest:
            latest_orders.append(type("O", (), dict(
                id=o.id, 
                title=o.title, 
                skills_required=o.skills_required,
                status=o.status, 
                elder_name=elders.get(o.elder_id,"—"),
                worker_name=workers.get(o.accepted_worker_id, None)
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
      from flask import render_template
      return render_template('order_detail.html', o=o, elder=elder, w=w, now=datetime.utcnow())
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
        skills = request.form.get("skills", "").strip()
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
    # 转换为模板友好对象
    ods = []
    workers = {u.id: u.name for u in db.query(User).filter(User.role=='worker').all()}
    for o in orders:
      ods.append(type('O', (), dict(id=o.id, title=o.title, status=o.status, skills_required=o.skills_required, worker_name=workers.get(o.accepted_worker_id))))
    from flask import render_template
    return render_template('elder_orders.html', orders=ods, status_label=status_label)
  finally:
    db.close()

@app.route('/elder/workers')
def elder_workers():
    db = db_session()
    try:
        ws = db.query(User).filter(User.role=='worker').all()
        workers = []
        for w in ws:
            workers.append(type('W', (), dict(id=w.id, name=w.name, price=w.price_per_hour, rating=w.rating, skills=w.skills_display)))
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
        # 根据当前用户角色决定数据范围：家属查看绑定老人，老人查看自己的，护工查看自己服务
        target_elder_id = None
        if require_family() and getattr(current_user, 'bound_elder_id', None):
            target_elder_id = current_user.bound_elder_id
        elif require_elder():
            target_elder_id = current_user.id

        # 近 14 天按日汇总
        q = db.query(func.date(CareLog.created_at).label('date'), func.sum(CareLog.duration_minutes).label('minutes'))
        if target_elder_id:
            q = q.join(Order, CareLog.order_id==Order.id).filter(Order.elder_id==target_elder_id)
        q = q.group_by('date').order_by('date').limit(14)
        dd = q.all()
        # 补齐日期序列（简单处理）
        labels = [str(r.date) for r in dd]
        values = [int(r.minutes or 0) for r in dd]

        # 护工时长占比
        wq = db.query(CareLog.worker_id, func.sum(CareLog.duration_minutes).label('minutes'))
        if target_elder_id:
            wq = wq.join(Order, CareLog.order_id==Order.id).filter(Order.elder_id==target_elder_id)
        wq = wq.group_by(CareLog.worker_id)
        wres = wq.all()
        worker_map = {u.id: u.name for u in db.query(User).filter(User.role=='worker').all()}
        worker_labels = [worker_map.get(r.worker_id, '未知') for r in wres]
        worker_values = [int(r.minutes or 0) for r in wres]

        total_minutes = sum(worker_values)
        total_workers = len([w for w in worker_values if w>0])
        avg_per_day = int(sum(values) / max(1, len(values))) if values else 0

        stats = { 'total_minutes': total_minutes, 'total_workers': total_workers, 'avg_per_day': avg_per_day }
        from flask import render_template
        return render_template('analytics.html', daily_labels=labels, daily_values=values, worker_labels=worker_labels, worker_values=worker_values, stats=stats)
    finally:
        db.close()

@app.route('/family/bind', methods=['GET','POST'])
def family_bind():
    if request.method == 'POST':
        flash('绑定成功（占位）','success')
        return redirect(url_for('index'))
    return rtemplate("""{% extends 'BASE' %}{% block content %}<div class='card p-4'><h5>绑定老人</h5><form method='post'><input class='form-control mb-2' name='email' placeholder='老人邮箱'><button class='btn btn-primary'>绑定</button></form></div>{% endblock %}""")

@app.route('/worker/log/<int:order_id>', methods=['GET','POST'])
def worker_log(order_id):
    if request.method == 'POST':
        flash('日志已保存（占位）','success')
        return redirect(url_for('worker_orders'))
    return rtemplate("""{% extends 'BASE' %}{% block content %}<div class='card p-4'>记录日志（占位）</div>{% endblock %}""")

@app.route('/worker/handover/<int:order_id>', methods=['POST','GET'])
def worker_handover(order_id):
    flash('已标记待接手（占位）','info')
    return redirect(url_for('worker_orders'))

@app.route('/worker/complete/<int:order_id>', methods=['POST','GET'])
def worker_complete(order_id):
    flash('已完成订单（占位）','success')
    return redirect(url_for('worker_orders'))

@app.route('/elder/logs/<int:order_id>')
def elder_logs(order_id):
    return rtemplate("""{% extends 'BASE' %}{% block content %}<div class='card p-4'>护理日志（占位）</div>{% endblock %}""")


@app.route('/worker/<int:worker_id>')
def worker_public(worker_id):
  db = db_session()
  try:
    w = db.get(User, worker_id)
    if not w or w.role != 'worker':
      abort(404)
    return rtemplate(WORKER_PUBLIC, w=w)
  finally:
    db.close()

@app.route('/worker/accept/<int:order_id>', methods=['POST','GET'])
def worker_accept(order_id):
    flash('接单成功（占位）','success')
    return redirect(url_for('worker_available_orders'))

@app.route('/worker/preview_logs/<int:order_id>')
def worker_preview_logs(order_id):
    return rtemplate("""{% extends 'BASE' %}{% block content %}<div class='card p-4'>历史日志预览（占位）</div>{% endblock %}""")

@app.route('/worker/orders')
def worker_orders():
    return rtemplate(WORKER_ORDERS, my_orders=[], history_orders=[] , skills=SKILL_CHOICES)

@app.route('/worker/profile', methods=['GET','POST'])
def worker_profile():
    return rtemplate(WORKER_PROFILE, u=current_user, skills=SKILL_CHOICES)

@app.route('/worker/available')
def worker_available_orders():
    return rtemplate(WORKER_AVAILABLE_ORDERS, available=[])

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
  if "--init-db" in sys.argv:
    print("[main] 初始化数据库中...")
    init_db()
    print("[main] 数据库初始化完成。")
  if "--seed" in sys.argv:
    print("[main] 插入示例数据...")
    try:
      from db import seed as db_seed
      db_seed()
    except Exception as e:
      print(f"[main] 插入示例数据失败: {e}")

  print("=" * 50)
  print("护理智联 平台启动中...")
  print("=" * 50)
  print(f"访问地址: http://localhost:5000")
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

  app.run(host="0.0.0.0", port=5000, debug=True)