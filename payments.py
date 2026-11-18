import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from solders.keypair import Keypair
from sqlalchemy.orm import Session

from auth import get_user_by_api_key, get_user_by_session
from config import LAMPORTS, MIN_LAMPORTS, PAYMENT_TTL_MIN, SOL_ADDR_RE, SUCCESS_REDIRECT, fernet
from db import get_db
from models import PaymentDB, UserDB
from solana_utils import calc_fee_lamports, calc_network_fee
from templates import render

router = APIRouter()

class Payment(BaseModel):
    address: str
    amount: float = Field(gt=0)
    redirect_url: Optional[str] = None

    @field_validator("address")
    @classmethod
    def check_address(cls, v: str) -> str:
        if not SOL_ADDR_RE.match(v):
            raise ValueError("invalid solana address")
        return v

def _create_payment_record(payment: Payment, user: UserDB, db: Session) -> str:
    pid = uuid.uuid4().hex
    fee_lamports = calc_fee_lamports(payment.amount)
    net_lamports = int(round(payment.amount * LAMPORTS))
    network_fee = calc_network_fee()
    total_lamports = fee_lamports + net_lamports + network_fee
    total = total_lamports / LAMPORTS

    if net_lamports < MIN_LAMPORTS or fee_lamports < MIN_LAMPORTS:
        raise HTTPException(status_code=400, detail="amount too small")

    kp = Keypair()
    secret_enc = fernet.encrypt(str(kp).encode()).decode()

    rec = PaymentDB(
        id=pid,
        shop_id=user.id,
        address=payment.address,
        amount=payment.amount,
        total=total,
        fee_lamports=fee_lamports,
        net_lamports=net_lamports,
        total_lamports=total_lamports,
        deposit_address=str(kp.pubkey()),
        deposit_secret_enc=secret_enc,
        redirect_url=payment.redirect_url,
    )
    db.add(rec)
    db.commit()
    return pid

@router.post("/ui/payment")
def ui_create_payment(
    request: Request,
    address: str = Form(...),
    amount: float = Form(...),
    redirect_url: str = Form(""),
    session: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    user = get_user_by_session(session, db)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    try:
        payment = Payment(address=address, amount=amount, redirect_url=redirect_url or None)
    except Exception as e:
        return JSONResponse({"error": f"Invalid input: {e}"}, status_code=400)
    try:
        pid = _create_payment_record(payment, user, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    url = str(request.base_url).rstrip("/") + f"/payment/{pid}"
    return {"url": url, "id": pid}

@router.post("/payment")
def create_payment(payment: Payment, request: Request, user: UserDB = Depends(get_user_by_api_key), db: Session = Depends(get_db)):
    pid = _create_payment_record(payment, user, db)
    return {"url": str(request.base_url).rstrip("/") + f"/payment/{pid}"}

@router.get("/payment/{pid}/status")
def payment_status(pid: str, db: Session = Depends(get_db)):
    rec = db.get(PaymentDB, pid)
    if not rec:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "id": rec.id,
        "status": rec.status,
        "paid": rec.status == "forwarded",
        "amount": rec.amount,
        "total": rec.total,
        "fee_tx": rec.fee_tx,
        "net_tx": rec.net_tx,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "ttl_minutes": PAYMENT_TTL_MIN,
    }

@router.get("/payment/{pid}")
def get_payment(pid: str, request: Request, db: Session = Depends(get_db)):
    rec = db.get(PaymentDB, pid)
    if not rec:
        raise HTTPException(status_code=404, detail="not found")

    target = rec.redirect_url or SUCCESS_REDIRECT
    if rec.status == "forwarded" and target:
        sep = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{sep}id={rec.id}", status_code=302)

    sol_uri = f"solana:{rec.deposit_address}?amount={rec.total}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=260x260&data={quote(sol_uri)}"
    status_label = {
        "pending": "Awaiting payment",
        "fee_sent": "Processing",
        "forwarded": "Completed",
        "expired": "Expired",
        "failed": "Failed",
    }.get(rec.status, rec.status)

    created_ts = int(rec.created_at.replace(tzinfo=timezone.utc).timestamp() * 1000) if rec.created_at else 0

    return render(request, "payment.html", {
        "rec": rec,
        "qr_url": qr_url,
        "status_label": status_label,
        "created_ts": created_ts,
        "ttl_minutes": PAYMENT_TTL_MIN,
    })