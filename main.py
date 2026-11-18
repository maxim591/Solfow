import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import Cookie, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from solana.rpc.async_api import AsyncClient
from sqlalchemy.orm import Session

import models
from auth import get_user_by_session, handle_callback, login_redirect, logout
from config import CORS_ORIGINS, RPC_URL
from db import Base, engine, get_db
from models import PaymentDB
from payments import router as payments_router
from solana_utils import poll_payments
from templates import render

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncClient(RPC_URL)
    task = asyncio.create_task(poll_payments(client))
    yield
    task.cancel()
    await client.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(payments_router)

@app.get("/")
def index(request: Request):
    return render(request, "index.html")

@app.get("/login")
def login():
    return login_redirect()

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str, db: Session = Depends(get_db)):
    return await handle_callback(request, code, db)

@app.post("/logout")
def logout_route(session: Optional[str] = Cookie(None), db: Session = Depends(get_db)):
    return logout(session, db)

@app.get("/dashboard")
def dashboard(request: Request, session: Optional[str] = Cookie(None), db: Session = Depends(get_db)):
    user = get_user_by_session(session, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    open_payments = (
        db.query(PaymentDB)
        .filter(PaymentDB.shop_id == user.id, PaymentDB.status.in_(["pending", "fee_sent"]))
        .order_by(PaymentDB.created_at.desc())
        .all()
    )
    paid_payments = (
        db.query(PaymentDB)
        .filter(PaymentDB.shop_id == user.id, PaymentDB.status == "forwarded")
        .order_by(PaymentDB.created_at.desc())
        .all()
    )
    open_count = len(open_payments)
    open_total = sum(p.amount for p in open_payments)
    paid_total = sum(p.amount for p in paid_payments)

    return render(request, "dashboard.html", {
        "user": user,
        "open_payments": open_payments,
        "paid_payments": paid_payments,
        "open_count": open_count,
        "open_total": open_total,
        "paid_total": paid_total,
    })

@app.post("/ui/payment/{pid}/delete")
def ui_delete_payment(pid: str, session: Optional[str] = Cookie(None), db: Session = Depends(get_db)):
    user = get_user_by_session(session, db)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    rec = db.get(PaymentDB, pid)
    if not rec or rec.shop_id != user.id:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if rec.status == "fee_sent":
        return JSONResponse({"error": "Payment is processing, cannot delete"}, status_code=400)
    db.delete(rec)
    db.commit()
    return {"deleted": pid}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)