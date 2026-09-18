"""Comprehensive Security Audit Tests for CodeSense.
Tests:
- JWT secret safety & environment validation
- Fernet credential encryption/decryption roundtrip
- Credential redaction in texts and logs
- Safe error handling without stack trace leakage
- Document download authorization, path-traversal prevention, and file existence checks
"""
from __future__ import annotations
import os
import pytest
from fastapi.testclient import TestClient
from app.config import settings, validate_security_settings, INSECURE_DEV_SECRET
from app.api.main import app
from app.analysis.security import redact_secrets
from app.auth.security import encrypt_credential, decrypt_credential, hash_password, create_token
from cryptography.fernet import Fernet
from app.models.database import SessionLocal
from app.models.models import User, Project, UserProjectAccess, GeneratedDocument, Base


@pytest.fixture
def client():
    return TestClient(app)


def test_jwt_security_validation(monkeypatch):
    """Verify security check warns or raises on insecure secret in production."""
    # Test production mode with default secret raises ValueError
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", INSECURE_DEV_SECRET)
    with pytest.raises(ValueError, match="CRITICAL SECURITY FAILURE"):
        validate_security_settings()

    # Test production mode with secure secret passes
    monkeypatch.setattr(settings, "JWT_SECRET", "very-strong-and-secure-random-token-xyz-123456789")
    validate_security_settings()  # Should not raise

    # Test development mode does not raise
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setattr(settings, "JWT_SECRET", INSECURE_DEV_SECRET)
    validate_security_settings()  # Should log warning, not raise


def test_fernet_credential_encryption_roundtrip(monkeypatch):
    """Verify Fernet encryption, decryption, and safety."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIAL_FERNET_KEY", key)

    secret = "ghp_PersonalAccessTokenABC123XYZ456SecretValue"
    ciphertext = encrypt_credential(secret)
    assert ciphertext.startswith("fernet:")
    assert ciphertext != secret
    decrypted = decrypt_credential(ciphertext)
    assert decrypted == secret

    # Empty string handling
    assert encrypt_credential("") == ""
    assert decrypt_credential("") == ""


def test_credential_redaction_patterns():
    """Verify comprehensive secret redaction against sensitive patterns."""
    sample_text = (
        "Database URL: postgresql://admin:SuperSecretPassword123@db.example.com:5432/mydb\n"
        "GitHub token: ghp_1234567890abcdefghijklmnopqrstuvwxyzAB\n"
        "AWS key: AKIAIOSFODNN7EXAMPLE and secret wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature\n"
        "Private RSA: -----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----\n"
    )
    redacted = redact_secrets(sample_text)

    # Assure all secrets are redacted
    assert "SuperSecretPassword123" not in redacted
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB" not in redacted
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in redacted
    assert "doNotLeakThisSignature" not in redacted
    assert "BEGIN RSA PRIVATE KEY" not in redacted
    assert "[REDACTED_" in redacted


def test_safe_error_handler_prevents_traceback_leak():
    """Verify unhandled server exceptions return safe JSON errors without stack traces."""
    safe_client = TestClient(app, raise_server_exceptions=False)
    # Define a temporary faulty endpoint to trigger an unhandled Exception
    @app.get("/test-internal-error")
    def faulty_endpoint():
        raise RuntimeError("Internal database connection failed with credentials dbuser:pass123")

    response = safe_client.get("/test-internal-error")
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "dbuser:pass123" not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text


def test_document_download_path_traversal_and_existence(client):
    """Verify document download protects against unauthorized access, missing files, and path traversal."""
    import app.models.database as dbmod
    Base.metadata.create_all(bind=dbmod.engine)
    db = dbmod.SessionLocal()
    try:
        # Create or fetch user and project
        u = db.query(User).filter(User.email == "secuser@example.com").first()
        if not u:
            u = User(email="secuser@example.com", password_hash=hash_password("pw1234"), role="analyst")
            db.add(u)
            db.flush()
        p = db.query(Project).filter(Project.name == "SecProject").first()
        if not p:
            p = Project(name="SecProject", repo_provider="github", repo_url="https://github.com/org/sec", default_branch="main")
            db.add(p)
            db.flush()
        pa = db.query(UserProjectAccess).filter(UserProjectAccess.user_id == u.id, UserProjectAccess.project_id == p.id).first()
        if not pa:
            pa = UserProjectAccess(user_id=u.id, project_id=p.id, access_level="viewer")
            db.add(pa)
        db.commit()

        # 1. Non-existent document ID -> 404
        token = create_token(u.email)
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get(f"/projects/{p.id}/docs/999999/download", headers=headers)
        assert resp.status_code == 404

        # 2. Document with missing file on disk -> 404
        doc_missing = GeneratedDocument(
            project_id=p.id,
            requested_by=u.id,
            scope="architecture",
            format="pdf",
            file_ref=os.path.join(settings.DOC_OUTPUT_DIR, "nonexistent_file.pdf"),
        )
        db.add(doc_missing)
        db.commit()

        resp_missing = client.get(f"/projects/{p.id}/docs/{doc_missing.id}/download", headers=headers)
        assert resp_missing.status_code == 404
        assert "not found" in resp_missing.json()["detail"].lower()

        # 3. Path traversal attempt -> 404
        doc_traversal = GeneratedDocument(
            project_id=p.id,
            requested_by=u.id,
            scope="architecture",
            format="pdf",
            file_ref=os.path.abspath("C:/Windows/System32/drivers/etc/hosts"),
        )
        db.add(doc_traversal)
        db.commit()

        resp_trav = client.get(f"/projects/{p.id}/docs/{doc_traversal.id}/download", headers=headers)
        assert resp_trav.status_code == 404

        # 4. Valid file inside DOC_OUTPUT_DIR -> 200 with Content-Disposition
        valid_file_path = os.path.join(settings.DOC_OUTPUT_DIR, f"sec_test_{p.id}.pdf")
        with open(valid_file_path, "wb") as f:
            f.write(b"%PDF-1.4 test content")

        doc_valid = GeneratedDocument(
            project_id=p.id,
            requested_by=u.id,
            scope="architecture",
            format="pdf",
            file_ref=valid_file_path,
        )
        db.add(doc_valid)
        db.commit()

        resp_valid = client.get(f"/projects/{p.id}/docs/{doc_valid.id}/download", headers=headers)
        assert resp_valid.status_code == 200
        assert "attachment" in resp_valid.headers.get("content-disposition", "").lower()
        assert resp_valid.content == b"%PDF-1.4 test content"

        # Cleanup test file
        if os.path.exists(valid_file_path):
            os.remove(valid_file_path)

    finally:
        db.close()
