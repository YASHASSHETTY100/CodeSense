from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import User, UserProjectAccess
from app.auth.security import decode_token

bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(401, "missing token")
    email = decode_token(creds.credentials)
    if not email:
        raise HTTPException(401, "invalid token")
    u = db.query(User).filter(User.email == email).first()
    if not u:
        raise HTTPException(401, "unknown user")
    return u


def require_project_access(project_id: int, user: User, db: Session,
                           min_level: str = "viewer") -> None:
    if user.role == "admin":
        return
    acc = db.query(UserProjectAccess).filter(
        UserProjectAccess.user_id == user.id,
        UserProjectAccess.project_id == project_id).first()
    if not acc:
        raise HTTPException(403, "no access to this project")
    order = {"viewer": 0, "contributor": 1, "owner": 2}
    if order.get(acc.access_level, 0) < order.get(min_level, 0):
        raise HTTPException(403, "insufficient access level")
