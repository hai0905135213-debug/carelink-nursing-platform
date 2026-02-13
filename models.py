from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey
from flask_login import UserMixin
from db import Base


class User(Base, UserMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    role = Column(String(16), nullable=False)  # worker/elder/family
    name = Column(String(64), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    phone = Column(String(32))
    password_hash = Column(String(255), nullable=False)
    price_per_hour = Column(Float)
    rating = Column(Float, default=5.0)
    skills_display = Column(String(255))
    elder_profile_complete = Column(Integer, default=0)
    bound_elder_id = Column(Integer, ForeignKey("users.id"))

    def is_worker(self): return self.role == "worker"
    def is_elder(self): return self.role == "elder"
    def is_family(self): return self.role == "family"


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    elder_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(120), nullable=False)
    description = Column(Text, nullable=False)
    skills_required = Column(String(255))
    status = Column(String(16), default="open")  # open/accepted/in_progress/completed/handover
    created_at = Column(DateTime, default=datetime.utcnow)
    accepted_worker_id = Column(Integer, ForeignKey("users.id"))
    handover_notes = Column(Text)  # 任务交接备注


class CareLog(Base):
    __tablename__ = "care_logs"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    worker_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    anomalies = Column(Text)
    duration_minutes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
