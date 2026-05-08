import os
from datetime import datetime
import re
from collections import defaultdict
import json
import hashlib
import urllib.request
import urllib.error

from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, jsonify, abort, session, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# 本模块拆分：配置、DB、模型、表单
from config import SECRET_KEY, status_label, now, DATABASE_URL
from db import db_session, init_db, engine, Base
from models import User, Order, CareLog, BindingRequest, OrderApplication
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

# 数据库迁移：在启动时确保表结构与新增列同步
init_db()

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
          <li class="nav-item"><a class="nav-link" href="{{ url_for('elder_applications') }}">已申请护工</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('elder_bind_requests') }}">绑定申请</a></li>
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
<div class="modal fade" id="orderBriefModal" tabindex="-1">
  <div class="modal-dialog modal-lg modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-lightning-charge-fill me-2 text-warning"></i>30秒可读摘要 + 待办清单</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div id="briefSummary" class="mb-3 text-secondary">加载中...</div>
        <div class="fw-semibold mb-2">待办清单</div>
        <ul id="briefTodo" class="mb-0"></ul>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.js-order-brief-btn');
    if (!btn) return;
    e.preventDefault();
    const orderId = btn.dataset.orderId;
    if (!orderId) return;
    const modalEl = document.getElementById('orderBriefModal');
    const modal = new bootstrap.Modal(modalEl);
    const summaryEl = document.getElementById('briefSummary');
    const todoEl = document.getElementById('briefTodo');
    summaryEl.textContent = '加载中...';
    todoEl.innerHTML = '';
    modal.show();
    fetch('/api/order/' + orderId + '/brief', { credentials: 'same-origin' })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          summaryEl.textContent = '加载失败：' + data.error;
          return;
        }
        summaryEl.textContent = data.summary || '暂无摘要';
        const todo = Array.isArray(data.todo) ? data.todo : [];
        if (!todo.length) todoEl.innerHTML = '<li>暂无待办</li>';
        else todoEl.innerHTML = todo.map(x => '<li>' + x + '</li>').join('');
      })
      .catch(() => {
        summaryEl.textContent = '加载失败，请稍后重试。';
      });
  });
</script>
	{% block scripts %}{% endblock %}
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

<h5 class="mt-4 mb-3">服务驻点与半径</h5>
<form id="locationForm" method="post" action="{{ url_for('worker_update_location') }}" class="card p-4">
  <p class="text-secondary small">拖拽地图上的标记设定您的服务驻点，并滑动调整服务半径。</p>
  <input type="hidden" name="longitude" id="longitude" value="{{ u.longitude or '116.397428' }}">
  <input type="hidden" name="latitude" id="latitude" value="{{ u.latitude or '39.90923' }}">
  <input type="hidden" name="service_radius" id="service_radius" value="{{ u.service_radius or 5 }}">
  <div class="mb-2"><input type="text" id="searchInput" class="form-control" placeholder="输入小区、大厦或地铁站进行搜索..."></div>
	  <div id="amapContainer" style="width:100%;height:400px;border-radius:8px;margin-bottom:12px;"></div>
  <div class="mb-2">
    <label class="form-label">服务半径：<strong id="radiusLabel">{{ u.service_radius or 5 }}</strong> 公里</label>
    <input type="range" id="radiusSlider" class="form-range" min="1" max="20" value="{{ u.service_radius or 5 }}" step="1">
  </div>
  <div class="small text-secondary mb-2">
    当前驻点：经度 <span id="dispLon">{{ u.longitude or '116.397428' }}</span>，纬度 <span id="dispLat">{{ u.latitude or '39.90923' }}</span>
  </div>
  <button type="submit" class="btn btn-success">保存驻点</button>
</form>
{% endblock %}
{% block scripts %}
<script src="https://webapi.amap.com/maps?v=2.0&key=67b5303d6e5df6b249332ca496266d44&plugin=AMap.AutoComplete,AMap.PlaceSearch"></script>
<script>
(function(){
  var lonEl = document.getElementById('longitude');
  var latEl = document.getElementById('latitude');
  var radiusEl = document.getElementById('service_radius');
  var slider = document.getElementById('radiusSlider');
  var radiusLabel = document.getElementById('radiusLabel');
  var dispLon = document.getElementById('dispLon');
  var dispLat = document.getElementById('dispLat');

  var lng = parseFloat(lonEl.value) || 116.397428;
  var lat = parseFloat(latEl.value) || 39.90923;
  var radius = parseFloat(radiusEl.value) || 5;

  var map = new AMap.Map('amapContainer', {
    center: [lng, lat],
    zoom: 13,
    resizeEnable: true
  });

  var marker = new AMap.Marker({
    position: [lng, lat],
    draggable: true,
    title: '拖拽我设置驻点'
  });
  map.add(marker);

  var circle = new AMap.Circle({
    center: [lng, lat],
    radius: radius * 1000,
    fillOpacity: 0.15,
    fillColor: '#1890ff',
    strokeColor: '#1890ff',
    strokeWeight: 2
  });
  map.add(circle);

  function updateUI(pos, r) {
    lonEl.value = pos.lng.toFixed(6);
    latEl.value = pos.lat.toFixed(6);
    dispLon.textContent = pos.lng.toFixed(6);
    dispLat.textContent = pos.lat.toFixed(6);
    marker.setPosition(pos);
    circle.setCenter(pos);
    circle.setRadius(r * 1000);
    radiusEl.value = r;
    radiusLabel.textContent = r;
  }

  marker.on('dragend', function(e) {
    updateUI(e.target.getPosition(), parseFloat(slider.value) || 5);
  });

  slider.addEventListener('input', function(){
    var r = parseFloat(this.value) || 5;
    circle.setRadius(r * 1000);
    radiusEl.value = r;
    radiusLabel.textContent = r;
  });

  // ===== POI 搜索与自动定位 =====
  var searchInput = document.getElementById('searchInput');
  if (searchInput) {
    AMap.plugin(['AMap.AutoComplete', 'AMap.PlaceSearch'], function () {
      var auto = new AMap.AutoComplete({ input: searchInput });
      var placeSearch = new AMap.PlaceSearch({ map: map });

      auto.on('select', function (e) {
        if (e.poi && e.poi.location) {
          var loc = e.poi.location;
          map.setZoomAndCenter(15, loc);
          var r = parseFloat(slider.value) || 5;
          updateUI({ lng: loc.lng, lat: loc.lat }, r);
        } else {
          placeSearch.search(searchInput.value, function (status, result) {
            if (status === 'complete' && result.poiList && result.poiList.pois.length) {
              var poi = result.poiList.pois[0];
              map.setZoomAndCenter(15, [poi.location.lng, poi.location.lat]);
              var r = parseFloat(slider.value) || 5;
              updateUI({ lng: poi.location.lng, lat: poi.location.lat }, r);
            }
          });
        }
      });
    });
  }

})();
</script>
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
      <button type="button" class="btn btn-sm btn-outline-dark js-order-brief-btn" data-order-id="{{ o.id }}">30秒摘要+待办</button>
      <form method="post" action="{{ url_for('worker_handover', order_id=o.id) }}"><button class="btn btn-sm btn-outline-warning">标记待接手</button></form>
      <form method="post" action="{{ url_for('worker_complete', order_id=o.id) }}"><button class="btn btn-sm btn-success">完成订单</button></form>
    </div>
  </div></div>
{% else %}<div class="text-secondary">暂无进行中的订单</div>{% endfor %}
</div>

<h5 class="mt-4 mb-2">我申请的订单</h5>
<div class="row g-3">
{% for o in applied_orders %}
  <div class="col-md-6"><div class="card p-3">
    <div class="d-flex justify-content-between">
      <div class="fw-semibold">{{ o.title }}</div>
      <span class="badge text-bg-warning">申请中</span>
    </div>
    <div class="small text-secondary">老人：{{ o.elder_name }}</div>
    <div class="small text-secondary">需：{{ o.skills_required }}</div>
    <div class="small text-secondary">价：{{ o.acceptable_price_range or '未设置' }} 元/小时</div>
    <div class="mt-2">
      <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('order_detail', order_id=o.id) }}">详情</a>
      <button type="button" class="btn btn-sm btn-outline-dark js-order-brief-btn" data-order-id="{{ o.id }}">30秒摘要+待办</button>
    </div>
  </div></div>
{% else %}<div class="text-secondary">暂无申请中的订单</div>{% endfor %}
</div>

<h5 class="mt-4 mb-2">历史接单</h5>
<div class="row g-3">
{% for o in history_orders %}
  <div class="col-md-6"><div class="card p-3">
    <div class="fw-semibold">{{ o.title }}</div>
    <div class="small text-secondary">状态：{{ {'open':'待接单','in_progress':'进行中','completed':'已完成','handover':'待接手'}[o.status] }}</div>
    <div class="mt-2">
      <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('order_detail', order_id=o.id) }}">详情</a>
      <button type="button" class="btn btn-sm btn-outline-dark js-order-brief-btn" data-order-id="{{ o.id }}">30秒摘要+待办</button>
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
    <div class="small text-secondary">价：{{ o.acceptable_price_range or '未设置' }} 元/小时</div>
    {% if o.handover_notes %}
    <div class="alert alert-warning small py-1 my-2">
      <strong>交接备注：</strong>{{ o.handover_notes }}
    </div>
    {% endif %}
    <div class="small text-warning mt-2"><i class="bi bi-exclamation-circle"></i> 接单/接手前请先阅读“30秒摘要+待办清单”</div>
    <form class="mt-2" method="post" action="{{ url_for('worker_accept', order_id=o.id) }}">
      <button class="btn btn-sm btn-primary" {% if o.applied %}disabled{% endif %}>{{ '申请中' if o.applied else '申请接单' }}</button>
      <button type="button" class="btn btn-sm btn-outline-dark js-order-brief-btn" data-order-id="{{ o.id }}">30秒摘要+待办</button>
      <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('order_detail', order_id=o.id) }}">详情</a>
      <a class="btn btn-sm btn-outline-info" href="{{ url_for('worker_preview_logs', order_id=o.id) }}">查看历史日志</a>
    </form>
  </div></div>
{% else %}<div class="text-secondary">暂无可接订单</div>{% endfor %}
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


def _parse_price_range(range_text):
    try:
        if not range_text or '-' not in str(range_text):
            return None, None
        a, b = str(range_text).split('-', 1)
        lo, hi = float(a.strip()), float(b.strip())
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi
    except Exception:
        return None, None


def _price_match_score(worker_price, range_text):
    lo, hi = _parse_price_range(range_text)
    if lo is None or hi is None:
        return 60.0
    mid = (lo + hi) / 2.0
    half = max(10.0, (hi - lo) / 2.0)
    p = float(worker_price or mid)
    dist = abs(p - mid)
    score = 100.0 - (dist / (half + 40.0)) * 100.0
    return max(35.0, min(100.0, score))




def _simple_skill_match(order_skills, worker_skills):
    req = {s.strip() for s in (order_skills or '').split(',') if s.strip()}
    own = {s.strip() for s in (worker_skills or '').split(',') if s.strip()}
    if not req:
        return 65.0
    inter = len(req.intersection(own))
    return max(35.0, min(100.0, 100.0 * inter / max(1, len(req))))


def _rank_applicants_with_ai(order_obj, candidates):
    """候选人排序：优先评分/权威/价格，技能匹配权重较小。"""
    if not candidates:
        return [], "暂无候选护工"

    for c in candidates:
        c["base_score"] = (
            0.55 * c["rating_avg"] +
            0.35 * c["price_match_score"] +
            0.10 * c["skill_match_score"]
        )

    fallback_sorted = sorted(candidates, key=lambda x: x["base_score"], reverse=True)
    fallback_reason = (
        f"综合评分与价格匹配度，推荐 {fallback_sorted[0]['display_name']} 优先接单。"
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key="sk-259952b41ae24b1e80c26ceaba58f778", base_url="https://api.deepseek.com")
        payload = {
            "order": {
                "id": order_obj.id,
                "title": order_obj.title,
                "description": order_obj.description or "",
                "skills_required": order_obj.skills_required or "",
                "acceptable_price_range": getattr(order_obj, "acceptable_price_range", None) or ""
            },
            "candidates": [
                {
                    "worker_id": c["worker_id"],
                    "worker_name": c["display_name"],
                    "rating_avg": round(c["rating_avg"], 2),
                    "price_match_score": round(c["price_match_score"], 2),
                    "skill_match_score": round(c["skill_match_score"], 2),
                    "skills_display": c["skills_display"] or "",
                    "price_per_hour": c["price_per_hour"] or 0
                } for c in candidates
            ]
        }
        prompt = (
            "你是护理平台的派单评估助手。请根据输入的 order 与 candidates 做排序。"
            "权重要求：评分与价格匹配是主导，技能匹配权重较小。"
            "请输出 JSON：{\"ranking\":[{\"worker_id\":1,\"score\":88.5}],\"top_reason\":\"...\"}。"
            "top_reason 请明确提及：评分、价格匹配，并简要提一嘴技能匹配。"
            "禁止输出 markdown。输入数据如下：\n" + json.dumps(payload, ensure_ascii=False)
        )
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        txt = (resp.choices[0].message.content or "").replace("```json", "").replace("```", "").strip()
        parsed = json.loads(txt)
        ranked_ids = [int(x.get("worker_id")) for x in parsed.get("ranking", []) if x.get("worker_id") is not None]
        rank_pos = {wid: i for i, wid in enumerate(ranked_ids)}
        ai_sorted = sorted(
            candidates,
            key=lambda x: (rank_pos.get(x["worker_id"], 10**6), -x["base_score"])
        )
        top_reason = parsed.get("top_reason") or fallback_reason
        return ai_sorted, top_reason
    except Exception:
        return fallback_sorted, fallback_reason


def _build_need_counts(orders):
    counts = defaultdict(int)
    aliases = {
        "翻身": ["翻身"],
        "测血压": ["测血压", "血压"],
        "康复训练": ["康复训练", "康复"],
        "喂药": ["喂药", "用药", "给药"],
        "测血糖": ["测血糖", "血糖"],
        "陪伴": ["陪伴", "聊天", "慰藉"],
        "洗澡": ["洗澡", "助浴", "擦洗"],
        "换药": ["换药", "换贴", "贴膏药", "伤口护理"],
        "吸痰": ["吸痰"],
        "导管护理": ["导管", "导尿"],
        "急救与复苏": ["急救", "复苏", "心肺复苏"],
        "辅助步行": ["下地走路", "步行", "行走", "走路"],
        "膝盖扭伤护理": ["半月板扭伤", "膝盖扭伤", "扭伤"]
    }
    def norm_text(s):
        return re.sub(r"\s+", "", (s or "").replace("，", ",").replace("。", ","))
    def normalize_label(part):
        p = norm_text(part)
        if not p:
            return None
        for label, kws in aliases.items():
            if any(k in p for k in kws):
                return label
        # 只保留结构化技能词，不把自由文本原句放进图表
        for s in SKILL_CHOICES:
            if norm_text(s) == p:
                return s
        return None
    for o in orders:
        combined = f"{getattr(o, 'skills_required', '') or ''},{getattr(o, 'description', '') or ''}"
        text_all = norm_text(combined)
        for k, kws in aliases.items():
            if any(norm_text(kw) in text_all for kw in kws):
                counts[k] += 1
        for part in text_all.split(","):
            label = normalize_label(part)
            if label:
                counts[label] += 1
    items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top = items[:12]
    return [x[0] for x in top], [x[1] for x in top]


def _deepseek_json(prompt, fallback=None):
    """Use raw HTTPS to call DeepSeek, avoiding external SDK dependency."""
    api_key = "sk-259952b41ae24b1e80c26ceaba58f778"
    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            raw = resp.read().decode("utf-8")
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content.replace("```json", "").replace("```", "").strip())
    except Exception:
        return fallback if fallback is not None else {}


def _build_admin_report_payload(db):
    workers = db.query(User).filter(User.role == "worker").all()
    elders = db.query(User).filter(User.role == "elder").all()
    families = db.query(User).filter(User.role == "family").all()
    orders = db.query(Order).order_by(Order.id.desc()).all()
    logs = db.query(CareLog).order_by(CareLog.created_at.desc()).limit(200).all()

    elder_alias = {}
    for idx, e in enumerate(sorted(elders, key=lambda x: x.id), start=1):
        elder_alias[e.id] = f"老人{chr(ord('A') + idx - 1)}" if idx <= 26 else f"老人{idx}"

    need_labels, need_values = _build_need_counts(orders)
    worker_payload = [{
        "id": w.id,
        "name": format_display_name(w.name, "worker"),
        "price_per_hour": w.price_per_hour,
        "rating": w.rating,
        "skills": w.skills_display
    } for w in workers]
    elder_payload = [{
        "alias": elder_alias.get(e.id, "老人X"),
        "order_count": sum(1 for o in orders if o.elder_id == e.id)
    } for e in elders]
    family_payload = [{
        "id": f.id,
        "name": format_display_name(f.name, "family"),
        "bound_elder": elder_alias.get(getattr(f, "bound_elder_id", None), "未绑定")
    } for f in families]
    order_payload = [{
        "id": o.id,
        "elder_alias": elder_alias.get(o.elder_id, "老人X"),
        "title": o.title,
        "skills_required": o.skills_required,
        "description": o.description,
        "acceptable_price_range": getattr(o, "acceptable_price_range", None),
        "status": o.status
    } for o in orders]
    log_payload = [{
        "order_id": l.order_id,
        "duration_minutes": l.duration_minutes,
        "content": l.content
    } for l in logs]
    return {
        "workers": workers,
        "elders": elders,
        "families": families,
        "orders": orders,
        "need_labels": need_labels,
        "need_values": need_values,
        "worker_payload": worker_payload,
        "elder_payload": elder_payload,
        "family_payload": family_payload,
        "order_payload": order_payload,
        "log_payload": log_payload
    }


def _generate_admin_report(data):
    need_labels = data["need_labels"]
    need_values = data["need_values"]
    worker_payload = data["worker_payload"]
    family_payload = data["family_payload"]
    prompt = (
        "你是医疗护理平台运营分析专家。请基于输入 JSON 生成专业报告，输出严格 JSON。"
        "必须包含字段：worker_insight, elder_insight, family_insight, supply_demand_insight, risk_insight, suggestions。"
        "要求：elder_insight 中不得出现任何真实姓名，只能使用给定 alias。"
        "重点分析护理需求结构与技能供给匹配，面向调研机构，语言专业。"
        "每个字段给出2-5条要点。输入如下：\n" + json.dumps({
            "workers": data["worker_payload"],
            "elders": data["elder_payload"],
            "families": data["family_payload"],
            "orders": data["order_payload"],
            "logs": data["log_payload"],
            "need_labels": need_labels,
            "need_values": need_values
        }, ensure_ascii=False)
    )
    fallback = {
        "worker_insight": [
            f"当前护工共 {len(worker_payload)} 人，已形成不同价格与技能层级。",
            "高评分护工集中在具备完整技能档案的人群。"
        ],
        "elder_insight": [
            "老人侧订单需求以基础生活照料与体征监测为主。",
            "部分订单存在复合需求（如翻身+测血压+康复训练），需要中高阶护工覆盖。"
        ],
        "family_insight": [
            f"家属端用户共 {len(family_payload)} 人，绑定老人比例对活跃度影响明显。",
            "家属更关注可视化日志与即时反馈，倾向选择评分更稳定的护工。"
        ],
        "supply_demand_insight": [
            "需求侧高频项与供给侧技能存在阶段性错配，建议加大高频技能培训。",
            "价格区间中段订单最集中，建议优化中段价格带护工供给。"
        ],
        "risk_insight": [
            "个别需求标签描述不标准，影响匹配精度。",
            "技能档案不完整的护工在高信任场景下转化率偏低。"
        ],
        "suggestions": [
            "建立按需求标签分层的护工培训与激励机制。",
            "完善订单需求结构化录入，减少自由文本歧义。",
            "对高频护理需求设置平台重点保障池。"
        ]
    }
    return _deepseek_json(prompt, fallback=fallback)


def _admin_report_to_markdown(report, need_labels, need_values, workers, elders, families, orders):
    def section(title, items):
        items = items if isinstance(items, list) else ([items] if items else [])
        body = "\n".join([f"- {x}" for x in items]) if items else "- 无"
        return f"## {title}\n{body}\n"

    need_table = "\n".join([f"| {need_labels[i]} | {need_values[i]} |" for i in range(len(need_labels))]) or "| 无 | 0 |"
    top_needs = ", ".join([f"{need_labels[i]}({need_values[i]})" for i in range(min(8, len(need_labels)))]) or "无"
    text = f"""# 平台用户信息调研报告

生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

## 平台概览
- 护工总数：{len(workers)}
- 老人总数：{len(elders)}
- 家属总数：{len(families)}
- 订单总数：{len(orders)}
- 高频护理需求（Top）：{top_needs}

## 护理需求统计表
| 需求标签 | 频次 |
|---|---|
{need_table}

{section("护工端洞察", report.get("worker_insight"))}
{section("老人端洞察（匿名）", report.get("elder_insight"))}
{section("家属端洞察", report.get("family_insight"))}
{section("供需结构洞察", report.get("supply_demand_insight"))}
{section("风险提示", report.get("risk_insight"))}
{section("运营建议", report.get("suggestions"))}
"""
    return text


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


@app.route("/api/order/<int:order_id>/brief")
@login_required
def api_order_brief(order_id):
    db = db_session()
    try:
        o = db.get(Order, order_id)
        if not o:
            return jsonify(error="订单不存在"), 404

        # 已完成订单做更严格权限，其他状态按已登录用户可读摘要
        if getattr(o, 'status', '') == 'completed':
            can_view = (
                o.elder_id == current_user.id or
                o.accepted_worker_id == current_user.id or
                (require_family() and getattr(current_user, 'bound_elder_id', None) == o.elder_id)
            )
            if not can_view:
                return jsonify(error="无权限访问该订单"), 403

        logs = db.query(CareLog).filter(CareLog.order_id == order_id).order_by(CareLog.created_at.desc()).limit(12).all()
        log_text = "\n".join([
            f"{l.created_at.strftime('%m-%d %H:%M')} | {l.duration_minutes}分钟 | {l.content}" +
            (f" | 异常:{l.anomalies}" if l.anomalies else "")
            for l in logs
        ]) or "暂无护理日志。"

        prompt = f"""
你是护理任务交接助手。请根据订单和日志生成“30秒可读摘要 + 待办清单”。
返回严格 JSON（不要 markdown）：
  "summary": "120字以内摘要",
  "todo": ["待办1", "待办2", "待办3"]
}}

订单标题：{o.title}
订单状态：{o.status}
护理需求：{o.skills_required or '无'}
护理地址：{getattr(o, 'address', None) or '未填写'}
描述：{o.description or ''}
最近日志：
{log_text}
"""
        fallback = {
            "summary": "该订单当前需要持续护理跟进，请先确认老人当前状态、既往记录和交接事项，再开始执行。",
            "todo": [
                "阅读近三天护理日志与异常备注",
                "核对今日护理目标（用药/训练/监测）",
                "完成后补充护理日志并标记异常"
            ]
        }
        result = _deepseek_json(prompt, fallback=fallback)

        # 记录“护工已阅读摘要”，用于接单/接手前提醒
        if require_worker():
            seen = session.get("order_brief_seen", [])
            if order_id not in seen:
                seen.append(order_id)
                session["order_brief_seen"] = seen[-50:]
                session.modified = True

        return jsonify(result)
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
        if not current_user.is_authenticated:
            return jsonify(error="未登录"), 401

        can_view = False
        if require_elder() and current_user.id == elder_id:
            can_view = True
        elif require_family() and getattr(current_user, 'bound_elder_id', None) == elder_id:
            can_view = True
        if not can_view:
            return jsonify(error="无权限查看该老人的护理时长"), 403

        rows = db.query(
            func.date(CareLog.created_at).label('date'),
            func.sum(CareLog.duration_minutes).label('minutes')
        ).join(Order, CareLog.order_id == Order.id).filter(
            Order.elder_id == elder_id
        ).group_by('date').order_by('date').all()

        result = [{"date": str(r.date), "minutes": int(r.minutes or 0)} for r in rows]
        if not result:
            labels, values, _, _ = _make_sample_data(14)
            result = [{"date": d, "minutes": int(values[i] or 0)} for i, d in enumerate(labels)]
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
            dict(title="生活照料", icon="bi-bag-heart", color="#0d9488", bg="rgba(13, 148, 136, 0.12)", items=["助浴、助餐","翻身、拍背","个人卫生清洁"]),
            dict(title="医疗护理", icon="bi-heart-pulse", color="#10b981", bg="rgba(16, 185, 129, 0.12)", items=["生命体征监测","药物管理","康复训练指导"]),
            dict(title="心理慰藉", icon="bi-chat-dots", color="#8b5cf6", bg="rgba(139, 92, 246, 0.12)", items=["陪伴聊天","心理疏导","读书读报"]),
            dict(title="居家服务", icon="bi-house-heart", color="#f59e0b", bg="rgba(245, 158, 11, 0.12)", items=["环境清洁","简单家务","陪同就医"]),
        ]
        bound_elder = None
        if current_user.is_authenticated and require_family() and getattr(current_user, 'bound_elder_id', None):
            bound_elder = db.get(User, current_user.bound_elder_id)
        # render from file-based template
        return render_template(
            'home.html',
            latest_orders=latest_orders,
            services=services,
            bound_elder=bound_elder,
            now=datetime.utcnow()
        )
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
        logs.append(type('L',(), dict(id=lg.id, order_id=lg.order_id, worker_id=lg.worker_id, worker_name=format_display_name(nm, role) if nm else '护工', content=lg.content, anomalies=lg.anomalies, duration_minutes=lg.duration_minutes, created_at=lg.created_at, health_skin=getattr(lg,'health_skin','正常'), health_mobility=getattr(lg,'health_mobility','平稳'), health_digestion=getattr(lg,'health_digestion','正常'), health_mental=getattr(lg,'health_mental','清醒'), photo_path=getattr(lg,'photo_path',None))))
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
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w1, content=log_rng.choice(contents_1), anomalies=None, duration_minutes=log_rng.randint(35, 55), created_at=today - timedelta(days=cutoff_days_ago + 2), health_skin='正常', health_mobility='平稳', health_digestion='正常', health_mental='清醒', photo_path=None)),
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w1, content=log_rng.choice(contents_1), anomalies=None, duration_minutes=log_rng.randint(22, 40), created_at=today - timedelta(days=cutoff_days_ago + 1), health_skin='正常', health_mobility='平稳', health_digestion='正常', health_mental='清醒', photo_path=None)),
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w2, content='交接：{}因事暂离，由本人接手后续护理'.format(w1), anomalies=None, duration_minutes=log_rng.randint(35, 50), created_at=today - timedelta(days=cutoff_days_ago), health_skin='正常', health_mobility='平稳', health_digestion='正常', health_mental='清醒', photo_path=None)),
          type('L',(), dict(id=0, order_id=order_id, worker_id=None, worker_name=w2, content='护工离职，无人接单状态持续至今。', anomalies=None, duration_minutes=log_rng.randint(25, 40), created_at=today - timedelta(days=cutoff_days_ago), health_skin='正常', health_mobility='平稳', health_digestion='正常', health_mental='清醒', photo_path=None)),
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
            created_at=today - timedelta(days=d),
            health_skin='正常', health_mobility='平稳', health_digestion='正常', health_mental='清醒', photo_path=None
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


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        key = (request.form.get("admin_key") or "").strip()
        if key == "regulate1999":
            session["is_admin"] = True
            flash("管理员登录成功", "success")
            return redirect(url_for("admin_dashboard"))
        flash("管理员密钥错误", "danger")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("管理员已退出", "info")
    return redirect(url_for("index"))


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
    db = db_session()
    try:
        workers = db.query(User).filter(User.role == "worker").order_by(User.id.asc()).all()
        elders = db.query(User).filter(User.role == "elder").order_by(User.id.asc()).all()
        families = db.query(User).filter(User.role == "family").order_by(User.id.asc()).all()
        orders = db.query(Order).order_by(Order.id.desc()).all()
        need_labels, need_values = _build_need_counts(orders)
        return render_template(
            "admin_dashboard.html",
            workers=workers,
            elders=elders,
            families=families,
            orders=orders,
            need_labels=need_labels,
            need_values=need_values
        )
    finally:
        db.close()


@app.route("/admin/risk-control")
def admin_risk_control():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))
        
    db = db_session()
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        risk_orders = db.query(Order).filter(Order.current_risk_level.in_(['medium', 'high'])).order_by(Order.created_at.desc()).all()
        
        today_high_risk = sum(1 for o in risk_orders if o.current_risk_level == 'high' and o.created_at >= today_start)
        saved_amount = sum(50000 if o.current_risk_level == 'high' else 10000 for o in risk_orders)
        
        risk_list = []
        for o in risk_orders:
            elder = db.get(User, o.elder_id)
            elder_name = elder.name if elder else '未知老人'
            risk_list.append({
                'id': o.id,
                'elder_name': elder_name,
                'risk_level': o.current_risk_level,
                'reason': o.risk_reason or '未记录明确原因'
            })
            
        return render_template("admin_risk_control.html", 
                               risk_orders=risk_list, 
                               today_high_risk=today_high_risk,
                               saved_amount=saved_amount)
    finally:
        db.close()

@app.route('/admin/risk_intervene/<int:order_id>', methods=['POST'])
def admin_risk_intervene(order_id):
    if not session.get("is_admin"):
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
        
    db = db_session()
    try:
        order = db.get(Order, order_id)
        if order and order.current_risk_level in ['medium', 'high']:
            order.current_risk_level = 'low'
            order.risk_reason = '管理员已介入并解除了警报：' + (order.risk_reason or '')
            db.commit()
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "订单不存在或无需纠正"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    finally:
        db.close()


@app.route("/admin/report", methods=["POST"])
def admin_report():
    if not session.get("is_admin"):
        return jsonify(error="无管理员权限"), 403
    db = db_session()
    try:
        data = _build_admin_report_payload(db)
        report = _generate_admin_report(data)
        need_labels, need_values = data["need_labels"], data["need_values"]
        return jsonify(report=report, need_labels=need_labels, need_values=need_values)
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        db.close()


@app.route("/admin/report/download", methods=["POST"])
def admin_report_download():
    if not session.get("is_admin"):
        return jsonify(error="无管理员权限"), 403
    db = db_session()
    try:
        data = _build_admin_report_payload(db)
        report = _generate_admin_report(data)
        md = _admin_report_to_markdown(
            report=report,
            need_labels=data["need_labels"],
            need_values=data["need_values"],
            workers=data["workers"],
            elders=data["elders"],
            families=data["families"],
            orders=data["orders"],
        )
        filename = f"platform_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"
        resp = make_response(md)
        resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        db.close()

# DB 会话通过 `from db import db_session` 提供（拆分到 db.py）






@app.route("/elder/create", methods=["GET","POST"])
@login_required
def elder_create():
    if not require_elder():
        flash("只有老人角色可以发布订单","warning")
        return redirect(url_for("index"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        acceptable_price_range = (request.form.get("acceptable_price_range") or "").strip()
        address = (request.form.get("address") or "").strip()
        allowed_ranges = {"20-60", "60-80", "80-100", "100-120", "120-140", "140-180"}
        if acceptable_price_range not in allowed_ranges:
            flash("请选择有效的可接受价格区间", "warning")
            return redirect(url_for("elder_create"))
        if not address:
            flash("请填写护理地址", "warning")
            return redirect(url_for("elder_create"))
        skills_list = request.form.getlist("skills")
        skills_other = request.form.get("skills_other", "").strip()
        if skills_other:
            skills_list.extend([s.strip() for s in skills_other.split(",") if s.strip()])
        skills = ", ".join(skills_list)
        db = db_session()
        try:
            o = Order(
                elder_id=current_user.id,
                title=title or "护理服务",
                description=description or "",
                skills_required=skills,
                acceptable_price_range=acceptable_price_range,
                address=address
            )
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


@app.route('/elder/applications')
@login_required
def elder_applications():
    if not require_elder():
        flash('只有老人可以查看申请排行', 'warning')
        return redirect(url_for('index'))

    db = db_session()
    try:
        from models import Rating
        orders = db.query(Order).filter(Order.elder_id == current_user.id).order_by(Order.id.desc()).all()
        order_ids = [o.id for o in orders]
        apps = db.query(OrderApplication).filter(
            OrderApplication.order_id.in_(order_ids),
            OrderApplication.status == 'pending'
        ).order_by(OrderApplication.applied_at.desc()).all() if order_ids else []

        by_order = defaultdict(list)
        for a in apps:
            by_order[a.order_id].append(a)

        workers = {w.id: w for w in db.query(User).filter(User.role == 'worker').all()}
        rankings = []
        for o in orders:
            items = by_order.get(o.id, [])
            if not items:
                continue
            candidates = []
            for ap in items:
                w = workers.get(ap.worker_id)
                if not w:
                    continue
                rs = db.query(
                    func.avg(Rating.score_attitude),
                    func.avg(Rating.score_ability),
                    func.avg(Rating.score_transparent)
                ).filter(Rating.worker_id == w.id).first()
                dims = [float(x) for x in rs if x is not None] if rs else []
                rating_avg = sum(dims) / len(dims) if dims else float(w.rating or 4.0)
                candidates.append({
                    "application_id": ap.id,
                    "worker_id": w.id,
                    "display_name": format_display_name(w.name, 'worker'),
                    "skills_display": w.skills_display or '',
                    "price_per_hour": float(w.price_per_hour or 0),
                    "rating_avg": float(rating_avg),
                    "price_match_score": _price_match_score(float(w.price_per_hour or 0), getattr(o, 'acceptable_price_range', None)),
                    "skill_match_score": _simple_skill_match(o.skills_required, w.skills_display)
                })
            ranked, top_reason = _rank_applicants_with_ai(o, candidates)
            rankings.append({
                "order": o,
                "candidates": ranked,
                "top_reason": top_reason
            })

        return render_template('elder_applications.html', rankings=rankings, now=datetime.utcnow())
    finally:
        db.close()


@app.route('/elder/order/<int:order_id>/accept-applicant/<int:worker_id>', methods=['POST'])
@login_required
def elder_accept_applicant(order_id, worker_id):
    if not require_elder():
        abort(403)
    db = db_session()
    try:
        o = db.get(Order, order_id)
        if not o or o.elder_id != current_user.id:
            abort(404)
        if o.status != 'open':
            flash('该订单已结束申请阶段，无法再次录用', 'warning')
            return redirect(url_for('elder_applications'))

        app_row = db.query(OrderApplication).filter(
            OrderApplication.order_id == order_id,
            OrderApplication.worker_id == worker_id,
            OrderApplication.status == 'pending'
        ).first()
        if not app_row:
            flash('该护工未在申请中', 'warning')
            return redirect(url_for('elder_applications'))

        o.accepted_worker_id = worker_id
        o.status = 'in_progress'
        app_row.status = 'accepted'
        app_row.reviewed_at = datetime.utcnow()
        db.add(o)
        db.add(app_row)

        db.query(OrderApplication).filter(
            OrderApplication.order_id == order_id,
            OrderApplication.worker_id != worker_id,
            OrderApplication.status == 'pending'
        ).update(
            {OrderApplication.status: 'rejected', OrderApplication.reviewed_at: datetime.utcnow()},
            synchronize_session=False
        )
        db.commit()
        flash('已录用该护工并开始执行订单', 'success')
        return redirect(url_for('elder_orders'))
    finally:
        db.close()

@app.route('/family/overview')
def family_overview():
    # 家属概览直接跳转到可视化仪表盘（若未登录则回首页）
    if not current_user.is_authenticated:
        return redirect(url_for('index'))
    return redirect(url_for('analytics'))




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
@login_required
def family_bind():
    if not require_family():
        flash('只有家属可以发起绑定申请', 'warning')
        return redirect(url_for('index'))

    db = db_session()
    try:
        if request.method == 'POST':
            elder_email = (request.form.get('email') or '').strip().lower()
            message = (request.form.get('message') or '').strip()
            if not elder_email:
                flash('请输入老人邮箱', 'warning')
                return redirect(url_for('family_bind'))

            elder = db.query(User).filter(func.lower(User.email) == elder_email, User.role == 'elder').first()
            if not elder:
                flash('未找到该老人账号，请确认邮箱是否正确', 'warning')
                return redirect(url_for('family_bind'))

            if getattr(current_user, 'bound_elder_id', None) == elder.id:
                flash('你已经绑定该老人账号', 'info')
                return redirect(url_for('family_bind'))

            if getattr(current_user, 'bound_elder_id', None) and current_user.bound_elder_id != elder.id:
                flash('你已绑定其他老人，若需更换请先联系管理员解绑', 'warning')
                return redirect(url_for('family_bind'))

            existing = db.query(BindingRequest).filter(
                BindingRequest.family_id == current_user.id,
                BindingRequest.elder_id == elder.id,
                BindingRequest.status == 'pending'
            ).first()
            if existing:
                flash('你已向该老人发起过申请，请等待老人确认', 'info')
                return redirect(url_for('family_bind'))

            req = BindingRequest(
                family_id=current_user.id,
                elder_id=elder.id,
                status='pending',
                message=message or None
            )
            db.add(req)
            db.commit()
            flash('绑定申请已发送，请等待老人确认', 'success')
            return redirect(url_for('family_bind'))

        bound_elder = None
        if getattr(current_user, 'bound_elder_id', None):
            bound_elder = db.get(User, current_user.bound_elder_id)

        reqs = db.query(BindingRequest).filter(
            BindingRequest.family_id == current_user.id
        ).order_by(BindingRequest.created_at.desc()).limit(10).all()
        elder_ids = [r.elder_id for r in reqs]
        elders = {u.id: u for u in db.query(User).filter(User.id.in_(elder_ids)).all()} if elder_ids else {}

        return render_template('family_bind.html', bound_elder=bound_elder, requests=reqs, elders=elders)
    finally:
        db.close()


@app.route('/elder/bind-requests')
@login_required
def elder_bind_requests():
    if not require_elder():
        flash('只有老人可以查看绑定申请', 'warning')
        return redirect(url_for('index'))

    db = db_session()
    try:
        requests = db.query(BindingRequest).filter(
            BindingRequest.elder_id == current_user.id
        ).order_by(BindingRequest.created_at.desc()).all()
        families = {u.id: u for u in db.query(User).filter(User.role == 'family').all()}
        return render_template('elder_bind_requests.html', requests=requests, families=families)
    finally:
        db.close()


@app.route('/elder/bind-requests/<int:request_id>/accept', methods=['POST'])
@login_required
def elder_accept_bind_request(request_id):
    if not require_elder():
        abort(403)

    db = db_session()
    try:
        req = db.get(BindingRequest, request_id)
        if not req or req.elder_id != current_user.id:
            abort(404)
        if req.status != 'pending':
            flash('该申请已处理', 'info')
            return redirect(url_for('elder_bind_requests'))

        family = db.get(User, req.family_id)
        if not family or family.role != 'family':
            flash('申请对应的家属账号不存在', 'warning')
            return redirect(url_for('elder_bind_requests'))

        family.bound_elder_id = current_user.id
        req.status = 'accepted'
        req.responded_at = datetime.utcnow()
        db.add(family)
        db.add(req)

        db.query(BindingRequest).filter(
            BindingRequest.family_id == family.id,
            BindingRequest.id != req.id,
            BindingRequest.status == 'pending'
        ).update(
            {
                BindingRequest.status: 'rejected',
                BindingRequest.responded_at: datetime.utcnow()
            },
            synchronize_session=False
        )
        db.commit()
        flash('已接受绑定申请，家属现在可以代为登录老人账号', 'success')
        return redirect(url_for('elder_bind_requests'))
    finally:
        db.close()


@app.route('/elder/bind-requests/<int:request_id>/reject', methods=['POST'])
@login_required
def elder_reject_bind_request(request_id):
    if not require_elder():
        abort(403)

    db = db_session()
    try:
        req = db.get(BindingRequest, request_id)
        if not req or req.elder_id != current_user.id:
            abort(404)
        if req.status == 'pending':
            req.status = 'rejected'
            req.responded_at = datetime.utcnow()
            db.add(req)
            db.commit()
            flash('已拒绝该绑定申请', 'info')
        else:
            flash('该申请已处理', 'info')
        return redirect(url_for('elder_bind_requests'))
    finally:
        db.close()


@app.route('/family/login-elder', methods=['POST'])
@login_required
def family_login_elder():
    if not require_family():
        abort(403)
    elder_id = getattr(current_user, 'bound_elder_id', None)
    if not elder_id:
        flash('你还没有绑定老人账号', 'warning')
        return redirect(url_for('family_bind'))

    db = db_session()
    try:
        elder = db.get(User, elder_id)
        if not elder or elder.role != 'elder':
            flash('绑定的老人账号无效，请重新绑定', 'warning')
            return redirect(url_for('family_bind'))
        login_user(elder)
        flash('已切换到老人账号', 'success')
        return redirect(url_for('index'))
    finally:
        db.close()

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
      photo = request.files.get('photo')
      photo_path = None
      if photo and photo.filename and _allowed_log_photo(photo.filename):
        os.makedirs(LOG_UPLOAD_FOLDER, exist_ok=True)
        ext = photo.filename.rsplit('.', 1)[1].lower()
        fn = secure_filename(f"log_{order_id}_{current_user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{ext}")
        path = os.path.join(LOG_UPLOAD_FOLDER, fn)
        photo.save(path)
        photo_path = f"log_uploads/{fn}"
      health_skin = request.form.get('health_skin', '正常')
      health_mobility = request.form.get('health_mobility', '平稳')
      health_digestion = request.form.get('health_digestion', '正常')
      health_mental = request.form.get('health_mental', '清醒')

      cl = CareLog(
          order_id=order_id, 
          worker_id=current_user.id, 
          content=content or '无', 
          anomalies=anomalies or None, 
          duration_minutes=duration, 
          photo_path=photo_path,
          health_skin=health_skin,
          health_mobility=health_mobility,
          health_digestion=health_digestion,
          health_mental=health_mental
      )
      db.add(cl)
      db.commit()

      # 调用 DeepSeek 进行风险评估
      prompt = f"""
你是一个专业的居家养老风险评估助手。请根据护工刚刚提交的护理日志和核心生活指标，评估该老人的当前重症/住院风险等级。
护工记录内容：{content}
异常备注：{anomalies or '无'}
1. 皮肤与体表：{health_skin}
2. 行动与跌倒：{health_mobility}
3. 进食与排泄：{health_digestion}
4. 精神与意识：{health_mental}

请严格输出 JSON 格式，包含两个字段：
- "level": 风险等级，只能是 "low", "medium", "high" 之一。如果所有指标都是正常/平稳且无明显异常，输出 "low"；如果有轻度异常输出 "medium"；如果有跌倒、拒食、嗜睡等严重情况输出 "high"。
- "reason": 给出简短的评估理由（20字以内）。
"""
      fallback = {"level": "low", "reason": "无法调用API，采取默认低风险"}
      result = _deepseek_json(prompt, fallback=fallback)
      
      # 更新 Order 风险级别
      order.current_risk_level = result.get('level', 'low')
      order.risk_reason = result.get('reason', '')
      db.commit()

      flash('日志已保存','success')
      return redirect(url_for('worker_log', order_id=order_id))

    # 查询日志并附带护工名称
    raw_logs = db.query(CareLog).filter(CareLog.order_id==order_id).order_by(CareLog.created_at.desc()).all()
    logs = []
    users = {u.id: (u.name, u.role) for u in db.query(User).all()}
    for lg in raw_logs:
      nm, role = users.get(lg.worker_id, (None, 'worker'))
      logs.append(type('L',(), dict(id=lg.id, order_id=lg.order_id, worker_id=lg.worker_id, worker_name=format_display_name(nm, role) if nm else None, content=lg.content, anomalies=lg.anomalies, duration_minutes=lg.duration_minutes, photo_path=getattr(lg, 'photo_path', None), created_at=lg.created_at)))
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
    db = db_session()
    try:
        o = db.get(Order, order_id)
        if o and o.accepted_worker_id == current_user.id:
            o.status = 'completed'
            db.add(o)
            db.commit()
            flash('已完成订单，感谢您的辛苦付出！','success')
        else:
            flash('无法完成该订单','danger')
        return redirect(url_for('worker_orders'))
    finally:
        db.close()
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
    flash('只有护工可以申请接单','warning')
    return redirect(url_for('index'))

  db = db_session()
  try:
    o = db.get(Order, order_id)
    if not o:
      flash('订单不存在','warning')
      return redirect(url_for('worker_available_orders'))
    if o.status not in ('open', 'handover'):
      flash('该订单当前不可申请','warning')
      return redirect(url_for('worker_available_orders'))

    seen = session.get("order_brief_seen", [])
    if order_id not in seen:
      flash('接单/接手前请先阅读“30秒可读摘要+待办清单”', 'warning')
      return redirect(url_for('worker_preview_logs', order_id=order_id))
    existing = db.query(OrderApplication).filter(
      OrderApplication.order_id == order_id,
      OrderApplication.worker_id == current_user.id
    ).first()
    if existing and existing.status == 'pending':
      flash('你已经申请过该订单，请等待老人审核','info')
      return redirect(url_for('worker_available_orders'))
    if existing and existing.status == 'rejected':
      existing.status = 'pending'
      existing.applied_at = datetime.utcnow()
      existing.reviewed_at = None
      db.add(existing)
    elif not existing:
      db.add(OrderApplication(order_id=order_id, worker_id=current_user.id, status='pending'))
    db.commit()
    flash('申请已提交，请等待老人确认','success')
    return redirect(url_for('worker_available_orders'))
  finally:
    db.close()

@app.route('/worker/preview_logs/<int:order_id>')
def worker_preview_logs(order_id):
    if not current_user.is_authenticated or not require_worker():
      flash('只有护工可以查看历史日志预览', 'warning')
      return redirect(url_for('index'))

    db = db_session()
    try:
      order = db.get(Order, order_id)
      if not order:
        flash('订单不存在', 'warning')
        return redirect(url_for('worker_available_orders'))

      raw_logs = db.query(CareLog).filter(CareLog.order_id == order_id).order_by(CareLog.created_at.desc()).all()
      users = {u.id: (u.name, u.role) for u in db.query(User).all()}
      logs = []
      for lg in raw_logs:
        nm, role = users.get(lg.worker_id, (None, 'worker'))
        logs.append(type('L', (), dict(
          id=lg.id,
          worker_name=format_display_name(nm, role) if nm else '护工',
          content=lg.content,
          anomalies=lg.anomalies,
          duration_minutes=lg.duration_minutes,
          photo_path=getattr(lg, 'photo_path', None),
          created_at=lg.created_at
        )))

      if not logs:
        from datetime import timedelta
        seed = order_id * 991 + (order.elder_id or 0) * 17
        rng = _seeded_rng(seed)
        worker_surnames = ['李', '肖', '陈', '王', '张', '赵', '刘', '周']
        wn = [s + '护工' for s in rng.sample(worker_surnames, 3)]
        contents = [
          '协助老人洗漱并完成晨间血压测量，状态平稳。',
          '午间协助进食与补水，进行15分钟肢体活动训练。',
          '按时提醒并协助用药，记录用药后反应正常。',
          '晚间陪伴沟通，进行睡前翻身与皮肤观察。',
          '完成康复训练动作指导，步态较前日更稳定。',
          '整理居住环境并复核次日护理计划。'
        ]
        anomalies_pool = [None, None, '午后轻微乏力，已休息后缓解。', '血压短时波动，已复测恢复正常。', '膝关节轻度不适，已减少训练强度。']
        base = datetime.utcnow() - timedelta(days=6)
        for i in range(7):
          logs.append(type('L', (), dict(
            id=0,
            worker_name=wn[i % len(wn)],
            content=contents[i % len(contents)],
            anomalies=anomalies_pool[rng.randint(0, len(anomalies_pool) - 1)],
            duration_minutes=rng.randint(35, 95),
            photo_path=None,
            created_at=base + timedelta(days=i, hours=rng.randint(8, 19), minutes=rng.randint(0, 59))
          )))
        logs.sort(key=lambda x: x.created_at, reverse=True)

      return render_template('worker_preview_logs.html', order=order, logs=logs)
    finally:
      db.close()

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
    applied_ids = [r.order_id for r in db.query(OrderApplication).filter(
      OrderApplication.worker_id == current_user.id,
      OrderApplication.status == 'pending'
    ).all()]
    applied_q = db.query(Order).filter(Order.id.in_(applied_ids), Order.accepted_worker_id != current_user.id).order_by(Order.id.desc()).all() if applied_ids else []

    elders = {u.id: format_display_name(u.name, 'elder') for u in db.query(User).filter(User.role=='elder').all()}

    my_orders = []
    for o in my_q:
      my_orders.append(type('O', (), dict(id=o.id, title=o.title, status=o.status, skills_required=o.skills_required, elder_name=elders.get(o.elder_id, '—'))))

    history_orders = []
    for o in history_q:
      history_orders.append(type('O', (), dict(id=o.id, title=o.title, status=o.status, skills_required=o.skills_required, elder_name=elders.get(o.elder_id, '—'))))

    applied_orders = []
    for o in applied_q:
      applied_orders.append(type('O', (), dict(
        id=o.id, title=o.title, status=o.status, skills_required=o.skills_required,
        acceptable_price_range=getattr(o, 'acceptable_price_range', None),
        elder_name=elders.get(o.elder_id, '—')
      )))

    return rtemplate(WORKER_ORDERS, my_orders=my_orders, applied_orders=applied_orders, history_orders=history_orders , skills=SKILL_CHOICES)
  finally:
    db.close()

@app.route('/worker/profile', methods=['GET','POST'])
def worker_profile():
    if not current_user.is_authenticated or not require_worker():
      flash('只有护工可以维护个人资料', 'warning')
      return redirect(url_for('index'))

    if request.method == 'POST':
      db = db_session()
      try:
        u = db.get(User, current_user.id)
        if not u or u.role != 'worker':
          flash('护工账号不存在', 'warning')
          return redirect(url_for('index'))

        price_raw = (request.form.get('price_per_hour') or '').strip()
        try:
          u.price_per_hour = float(price_raw) if price_raw else None
        except Exception:
          flash('价格格式不正确', 'warning')
          return redirect(url_for('worker_profile'))

        skills = [s.strip() for s in request.form.getlist('skills') if s and s.strip()]
        # 去重并保持顺序，避免重复技能显示
        seen = set()
        skills = [s for s in skills if not (s in seen or seen.add(s))]
        u.skills_display = ", ".join(skills) if skills else None

        phone = (request.form.get('phone') or '').strip()
        u.phone = phone or None

        db.add(u)
        db.commit()
        flash('资料保存成功', 'success')
      finally:
        db.close()
      return redirect(url_for('worker_profile'))

    return rtemplate(WORKER_PROFILE, u=current_user, skills=SKILL_CHOICES)

@app.route('/worker/update_location', methods=['POST'])
@login_required
def worker_update_location():
    db = db_session()
    try:
        u = db.get(User, current_user.id)
        if not u or u.role != 'worker':
            flash('只有护工可以设置服务驻点', 'warning')
            return redirect(url_for('index'))

        lon = (request.form.get('longitude') or '').strip()
        lat = (request.form.get('latitude') or '').strip()
        radius = (request.form.get('service_radius') or '').strip()

        if lon and lat:
            try:
                u.longitude = float(lon)
                u.latitude = float(lat)
            except (ValueError, TypeError):
                flash('经纬度格式不正确', 'warning')
                return redirect(url_for('worker_profile'))

        if radius:
            try:
                u.service_radius = int(float(radius))
            except (ValueError, TypeError):
                flash('服务半径格式不正确', 'warning')
                return redirect(url_for('worker_profile'))

        db.add(u)
        db.commit()
        flash('服务驻点保存成功', 'success')
    finally:
        db.close()
    return redirect(url_for('worker_profile'))

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
LOG_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'log_uploads')
LOG_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _allowed_log_photo(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in LOG_ALLOWED_EXTENSIONS

@app.route('/worker/available')
def worker_available_orders():
  if not current_user.is_authenticated or not require_worker():
    flash('只有护工可以查看可接订单','warning')
    return redirect(url_for('index'))

  db = db_session()
  try:
    # 可接订单：状态为 open 或 handover（待接手）
    orders = db.query(Order).filter(Order.status.in_(['open', 'handover'])).order_by(Order.id.desc()).all()
    order_ids = [o.id for o in orders]
    app_map = {}
    if order_ids:
      app_map = {r.order_id: r.status for r in db.query(OrderApplication).filter(
        OrderApplication.worker_id == current_user.id,
        OrderApplication.order_id.in_(order_ids)
      ).all()}
    elders = {u.id: format_display_name(u.name, 'elder') for u in db.query(User).filter(User.role=='elder').all()}
    available = []
    for o in orders:
      available.append(type('O', (), dict(
        id=o.id,
        title=o.title,
        status=o.status,
        skills_required=o.skills_required,
        acceptable_price_range=getattr(o, 'acceptable_price_range', None),
        handover_notes=getattr(o, 'handover_notes', None),
        applied=(app_map.get(o.id) == 'pending'),
        elder_name=elders.get(o.elder_id, '—')
      )))
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

    # 提取 scripts block
    scripts_content = ""
    sm = re.search(r"{%\s*block\s+scripts\s*%}(.*?){%\s*endblock\s*%}", body, re.S)
    if sm:
        scripts_content = sm.group(1).strip()
        body = body.replace(sm.group(0), "").strip()

    m = re.search(r"{%\s*block\s+content\s*%}(.*?){%\s*endblock\s*%}", body, re.S)
    if m:
      body = m.group(1).strip()

    marker = "{% block content %}{% endblock %}"
    if marker in BASE:
      full = BASE.replace(marker, "{% block content %}\n" + body + "\n{% endblock %}")
    else:
      full = BASE + "\n" + body

    if scripts_content:
        scripts_marker = "{% block scripts %}{% endblock %}"
        if scripts_marker in full:
            full = full.replace(scripts_marker, "{% block scripts %}\n" + scripts_content + "\n{% endblock %}")
        else:
            full = full + "\n" + scripts_content

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



  app.run(host="0.0.0.0", port=args.port, debug=True)
