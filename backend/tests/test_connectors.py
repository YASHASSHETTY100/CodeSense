"""Unit: connectors parse + credential crypto round-trip."""
from app.connectors import GitHubConnector, GitLabConnector
from app.auth.security import encrypt_credential, decrypt_credential


def test_github_parse():
    c = GitHubConnector()
    assert c.parse_repo_url("https://github.com/acme/shop.git") == {"owner": "acme", "repo": "shop"}


def test_gitlab_parse():
    c = GitLabConnector()
    assert "path" in c.parse_repo_url("https://gitlab.com/group/sub/repo.git")


def test_credential_roundtrip():
    ref = encrypt_credential("secret-pat-123")
    assert decrypt_credential(ref) == "secret-pat-123"
    assert "secret-pat" not in ref or ref.startswith("b64:") or ref.startswith("fernet:")
