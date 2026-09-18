from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import User, UserProjectAccess, Project
from app.api.deps import current_user

router = APIRouter(prefix="/admin", tags=["admin"])


class Grant(BaseModel):
    project_id: int
    access_level: str = "viewer"


def _admin(u: User):
    if u.role != "admin":
        raise HTTPException(403, "admin only")


@router.get("/users")
def users(u: User = Depends(current_user), db: Session = Depends(get_db)):
    _admin(u)
    all_users = db.query(User).all()
    result = []
    for x in all_users:
        access_rows = db.query(UserProjectAccess, Project).join(
            Project, UserProjectAccess.project_id == Project.id
        ).filter(UserProjectAccess.user_id == x.id).all()
        projects = [{
            "project_id": p.id,
            "project_name": p.name,
            "access_level": acc.access_level
        } for acc, p in access_rows]
        result.append({
            "id": x.id,
            "email": x.email,
            "name": x.name,
            "role": x.role,
            "projects": projects
        })
    return result


@router.post("/users/{uid}/projects")
def grant(uid: int, b: Grant, u: User = Depends(current_user), db: Session = Depends(get_db)):
    _admin(u)
    if b.access_level not in ("owner", "contributor", "viewer"):
        raise HTTPException(400, "bad access_level")
    if not db.query(Project).filter(Project.id == b.project_id).first():
        raise HTTPException(404, "project not found")
    ex = db.query(UserProjectAccess).filter(
        UserProjectAccess.user_id == uid, UserProjectAccess.project_id == b.project_id).first()
    if ex:
        ex.access_level = b.access_level
    else:
        db.add(UserProjectAccess(user_id=uid, project_id=b.project_id, access_level=b.access_level))
    db.commit()
    return {"ok": True}


@router.delete("/users/{uid}/projects/{pid}")
def revoke(uid: int, pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    _admin(u)
    acc = db.query(UserProjectAccess).filter(
        UserProjectAccess.user_id == uid, UserProjectAccess.project_id == pid
    ).first()
    if not acc:
        raise HTTPException(404, "assignment not found")
    db.delete(acc)
    db.commit()
    return {"ok": True, "revoked": True}


@router.get("/projects/{pid}/members")
def project_members(pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    _admin(u)
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "project not found")
    members = db.query(UserProjectAccess, User).join(
        User, UserProjectAccess.user_id == User.id
    ).filter(UserProjectAccess.project_id == pid).all()
    return [{
        "user_id": usr.id,
        "email": usr.email,
        "name": usr.name,
        "role": usr.role,
        "access_level": acc.access_level
    } for acc, usr in members]
