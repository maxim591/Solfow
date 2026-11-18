import secrets
from typing import Optional
from urllib.parse import urlencode

import os

import httpx
from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI
from db import get_db
from models import SessionDB, UserDB
from templates import error_page

def _new_api_key() -> str:
    return "sk_" + secrets.token_urlsafe(32)

def get_user_by_session(token: Optional[str], db: Session) -> Optional[UserDB]:
    if not token:
        return None
    sess = db.get(SessionDB, token)
    if not sess:
        return None
    return db.get(UserDB, sess.user_id)

def get_user_by_api_key(x_api_key: str = Header(...), db: Session = Depends(get_db)) -> UserDB:
    user = db.query(UserDB).filter(UserDB.api_key == x_api_key).first()
    if not user:
        raise HTTPException(status_code=401, detail="invalid api key")
    return user

def login_redirect() -> RedirectResponse:
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify email",
    }
    url = "https://discord.com/oauth2/authorize?" + urlencode(params)
    return RedirectResponse(url, status_code=302)

async def handle_callback(request: Request, code: str, db: Session):
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://discord.com/api/v10/oauth2/token", data=data, headers=headers)
        if token_resp.status_code != 200:
            return error_page(request, "Discord Login fehlgeschlagen.", 400, "/")
        access_token = token_resp.json().get("access_token")

        user_headers = {"Authorization": f"Bearer {access_token}"}
        user_resp = await client.get("https://discord.com/api/v10/users/@me", headers=user_headers)
        if user_resp.status_code != 200:
            return error_page(request, "User-Daten konnten nicht geladen werden.", 400, "/")
        discord_user = user_resp.json()

    discord_id = discord_user["id"]
    username = discord_user.get("username", "unknown")
    email = discord_user.get("email")

    user = db.get(UserDB, discord_id)
    if not user:
        user = UserDB(id=discord_id, username=username, email=email, api_key=_new_api_key())
        db.add(user)
        db.commit()
    else:
        if user.username != username or user.email != email:
            user.username = username
            user.email = email
            db.commit()

    token = secrets.token_urlsafe(32)
    db.add(SessionDB(token=token, user_id=user.id))
    db.commit()

    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(
    "session", token,
    httponly=True,
    samesite="lax",
    secure=os.getenv("ENV", "dev") == "prod",  # nur in Prod
    max_age=60*60*24*30,
)
    return resp

def logout(session: Optional[str], db: Session) -> RedirectResponse:
    if session:
        s = db.get(SessionDB, session)
        if s:
            db.delete(s)
            db.commit()
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("session")
    return resp