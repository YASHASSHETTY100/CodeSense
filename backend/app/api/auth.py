from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import User
from app.auth.security import hash_password, verify_password, create_token
from app.api.deps import current_user

router = APIRouter(prefix="/auth", tags=["auth"])


import re


class Signup(BaseModel):
    email: str
    name: str = ""
    password: str
    confirm_password: str = ""
    role: str = ""


class Login(BaseModel):
    email: str
    password: str


@router.post("/signup")
def signup(b: Signup, db: Session = Depends(get_db)):
    email = b.email.strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Please provide a valid email address.")
    if len(b.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters long.")
    if b.confirm_password and b.password != b.confirm_password:
        raise HTTPException(400, "Passwords do not match.")

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "An account with this email address already exists. Please log in.")

    # Bootstrap behavior: First registered account becomes admin, all subsequent default to normal user
    total_users = db.query(User).count()
    assigned_role = "admin" if total_users == 0 else "pm"

    u = User(
        email=email,
        name=b.name.strip(),
        password_hash=hash_password(b.password),
        role=assigned_role
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return {
        "token": create_token(u.email),
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "message": "Account created successfully. Please log in."
    }


@router.post("/login")
def login(b: Login, db: Session = Depends(get_db)):
    email = b.email.strip().lower()
    u = db.query(User).filter(User.email == email).first()
    if not u or not verify_password(b.password, u.password_hash or ""):
        raise HTTPException(401, "Invalid email or password.")
    return {"token": create_token(u.email), "email": u.email, "name": u.name, "role": u.role}


@router.get("/me")
def me(u: User = Depends(current_user)):
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}


@router.get("/github/login")
def github_login():
    from app.config import settings
    if not settings.GITHUB_CLIENT_ID:
        return {"detail": "GitHub OAuth not configured; use PAT credential per project."}
    return {"url": f"https://github.com/login/oauth/authorize?client_id={settings.GITHUB_CLIENT_ID}"}


@router.post("/github/callback")
def github_callback(code: str = "", db: Session = Depends(get_db), u: User = Depends(current_user)):
    # TODO(agent): exchange code for token via GitHub API; store encrypted on user profile.
    return {"detail": "GitHub OAuth callback stub — PAT per project is the supported path.", "code_received": bool(code)}
