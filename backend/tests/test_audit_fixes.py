"""Regression tests for the post-audit hardening (Wave A):
secret detection, atomic writes, stronger command blocking, corrected pricing."""
import os

from app import config, safe_fs, security, cost_tracker


# ── Secret detection (broader than the exact SECRET_FILES set) ───────────────────

def test_is_secret_path_catches_variants():
    assert config.is_secret_path(".env")
    assert config.is_secret_path("backend/.env")
    assert config.is_secret_path(".ENV")               # case-insensitive
    assert config.is_secret_path(".env.production")
    assert config.is_secret_path("config/server.pem")
    assert config.is_secret_path("deploy.key")
    assert config.is_secret_path("id_rsa")
    assert config.is_secret_path("credentials.json")


def test_is_secret_path_allows_normal_files():
    assert not config.is_secret_path("main.py")
    assert not config.is_secret_path("src/app.tsx")
    assert not config.is_secret_path("README.md")
    assert not config.is_secret_path("environment.py")  # not an .env file


# ── Corrected Anthropic pricing ──────────────────────────────────────────────────

def test_opus_45_priced_at_5_25():
    assert cost_tracker.price("anthropic", "claude-opus-4-5") == (5.0, 25.0)


def test_haiku_45_priced_at_1_5():
    assert cost_tracker.price("anthropic", "claude-haiku-4-5") == (1.0, 5.0)


# ── Atomic write keeps content verbatim (no CRLF doubling) ───────────────────────

def test_atomic_write_preserves_content(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    body = "line1\nline2\nácéntòs y ñ\n"
    safe_fs.write_file_safe("code.py", body)
    raw = (tmp_path / "code.py").read_bytes()
    assert b"\r\r\n" not in raw                      # no CRLF doubling
    assert raw.decode("utf-8") == body               # exact roundtrip, accents intact


def test_overwrite_creates_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    safe_fs.write_file_safe("n.txt", "v1")
    _, _, backup = safe_fs.write_file_safe("n.txt", "v2")
    assert backup is not None and os.path.exists(backup)


# ── Stronger destructive-command blocking ────────────────────────────────────────

def test_blocks_powershell_recursive_delete():
    assert security.blocked_command("Remove-Item -Recurse -Force C:\\data") is not None


def test_blocks_git_push_dash_f():
    assert security.blocked_command("git push -f origin main") is not None


def test_blocks_dd_of_device():
    assert security.blocked_command("dd of=/dev/sda bs=1M") is not None


def test_allows_benign_commands():
    assert security.blocked_command("npm run dev") is None
    assert security.blocked_command("Get-Content README.md") is None
    assert security.blocked_command("python -m pytest") is None


# ── Auth fails closed without a signing secret ───────────────────────────────────

def test_auth_fails_closed_without_secret(monkeypatch):
    import pytest
    from app import auth
    monkeypatch.delenv("SWARM_SECRET", raising=False)
    monkeypatch.delenv("SWARM_AUTH_TOKEN", raising=False)
    # No signing key → no token can be trusted, and we refuse to mint one.
    assert auth.verify_token("forged.signature") is None
    with pytest.raises(ValueError):
        auth.issue_token("attacker", role="owner")


# ── Checkpoints never snapshot secrets ───────────────────────────────────────────

def test_checkpoint_excludes_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / "app.py").write_text("x")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-secret")
    from app import checkpoints
    cp = checkpoints.create_checkpoint("c")
    assert "app.py" in cp["files"]
    assert ".env" not in cp["files"]  # secret excluded from the snapshot
