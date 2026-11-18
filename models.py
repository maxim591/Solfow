from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String

from db import Base

class UserDB(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    username = Column(String, nullable=True)
    email = Column(String, nullable=True)
    api_key = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

class SessionDB(Base):
    __tablename__ = "sessions"
    token = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

class PaymentDB(Base):
    __tablename__ = "payments"
    id = Column(String, primary_key=True)
    shop_id = Column(String, nullable=True)
    address = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    fee_lamports = Column(Integer, nullable=False)
    net_lamports = Column(Integer, nullable=False)
    total_lamports = Column(Integer, nullable=False)
    deposit_address = Column(String, nullable=False)
    deposit_secret_enc = Column(String, nullable=False)
    status = Column(String, default="pending")
    fee_tx = Column(String, nullable=True)
    net_tx = Column(String, nullable=True)
    redirect_url = Column(String, nullable=True)
    lock_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))