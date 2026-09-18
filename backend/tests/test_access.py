"""Access-control: user without mapping gets 403 on project endpoints."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import app.models.database as dbmod
from app.models.models import Base, User, Project
from app.api.main import app
from app.auth.security import create_token

from sqlalchemy.pool import StaticPool
eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                    poolclass=StaticPool)
Base.metadata.create_all(bind=eng)
dbmod.engine = eng
dbmod.SessionLocal = sessionmaker(bind=eng)
dbmod.get_db.__wrapped__ if hasattr(dbmod.get_db, "__wrapped__") else None

# override dep
from app.models.database import get_db
def _ov():
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()
app.dependency_overrides[get_db] = _ov

S = sessionmaker(bind=eng)()
admin = User(email="admin@x.com", password_hash="x", role="admin")
owner = User(email="owner@x.com", password_hash="x", role="pm")
stranger = User(email="stranger@x.com", password_hash="x", role="pm")
S.add_all([admin, owner, stranger])
S.flush()
proj = Project(name="P", repo_url="https://github.com/a/b")
S.add(proj)
S.flush()
from app.models.models import UserProjectAccess
S.add(UserProjectAccess(user_id=owner.id, project_id=proj.id, access_level="owner"))
S.commit()
PID = proj.id


def test_forbidden():
    c = TestClient(app)
    r = c.get(f"/projects/{PID}", headers={"Authorization": f"Bearer {create_token('stranger@x.com')}"})
    assert r.status_code == 403, r.text


def test_allowed():
    c = TestClient(app)
    r = c.get(f"/projects/{PID}", headers={"Authorization": f"Bearer {create_token('owner@x.com')}"})
    assert r.status_code == 200, r.text


def test_unauthorized_user_blocked_on_all_qa_endpoints():
    c = TestClient(app)
    headers = {"Authorization": f"Bearer {create_token('stranger@x.com')}"}

    # Summary
    assert c.get(f"/projects/{PID}/summary", headers=headers).status_code == 403
    # Ask
    assert c.post(f"/projects/{PID}/ask", headers=headers, json={"question": "test"}).status_code == 403
    # Trace flow
    assert c.post(f"/projects/{PID}/trace-flow", headers=headers, json={"question": "test"}).status_code == 403
    # Analyze enhancement
    assert c.post(f"/projects/{PID}/analyze-enhancement", headers=headers, json={"request": "test"}).status_code == 403
    # Generate doc
    assert c.post(f"/projects/{PID}/generate-doc", headers=headers, json={"scope": "full", "format": "docx"}).status_code == 403


def test_admin_user_management_and_project_assignment():
    c = TestClient(app)
    admin_headers = {"Authorization": f"Bearer {create_token('admin@x.com')}"}
    stranger_headers = {"Authorization": f"Bearer {create_token('stranger@x.com')}"}

    # Stranger blocked from admin
    assert c.get("/admin/users", headers=stranger_headers).status_code == 403

    # Admin lists users with projects
    r = c.get("/admin/users", headers=admin_headers)
    assert r.status_code == 200
    users = r.json()
    assert len(users) >= 3
    assert any("projects" in u for u in users)

    # Admin grants stranger viewer access
    r_grant = c.post(f"/admin/users/{stranger.id}/projects", headers=admin_headers,
                     json={"project_id": PID, "access_level": "viewer"})
    assert r_grant.status_code == 200

    # Stranger can now access project
    assert c.get(f"/projects/{PID}", headers=stranger_headers).status_code == 200

    # Admin views project members
    r_members = c.get(f"/admin/projects/{PID}/members", headers=admin_headers)
    assert r_members.status_code == 200
    assert any(m["user_id"] == stranger.id for m in r_members.json())

    # Admin revokes access
    r_revoke = c.delete(f"/admin/users/{stranger.id}/projects/{PID}", headers=admin_headers)
    assert r_revoke.status_code == 200

    # Stranger blocked again
    assert c.get(f"/projects/{PID}", headers=stranger_headers).status_code == 403

