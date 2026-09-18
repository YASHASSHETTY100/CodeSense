"""Password hashing + JWT + Fernet credential encryption."""
from __future__ import annotations
import base64
from datetime import datetime, timedelta
from jose import jwt
import bcrypt
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (), {"__version__": getattr(bcrypt, "__version__", "4.0.0")})

from passlib.context import CryptContext
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(pw)


def verify_password(pw: str, h: str) -> bool:
    return pwd_ctx.verify(pw, h)


def create_token(sub: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode({"sub": sub, "exp": exp}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(tok: str) -> str | None:
    try:
        return jwt.decode(tok, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])["sub"]
    except Exception:
        return None


def _fernet() -> Fernet | None:
    if not settings.CREDENTIAL_FERNET_KEY:
        return None
    return Fernet(settings.CREDENTIAL_FERNET_KEY.encode())


def encrypt_credential(raw: str) -> str:
    f = _fernet()
    if not f or not raw:
        # obfuscated fallback (NOT prod-grade); documented in DECISIONS.md
        return "b64:" + base64.b64encode(raw.encode()).decode() if raw else ""
    return "fernet:" + f.encrypt(raw.encode()).decode()


def decrypt_credential(ref: str) -> str:
    if not ref:
        return ""
    if ref.startswith("b64:"):
        return base64.b64decode(ref[4:].encode()).decode()
    if ref.startswith("fernet:"):
        f = _fernet()
        if not f:
            raise ValueError("credential encrypted with Fernet but no key configured")
        return f.decrypt(ref[7:].encode()).decode()
    return ref  # legacy plaintext
