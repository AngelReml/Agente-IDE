"""Auth, SSRF guard and destructive-command blocking."""
import importlib


def _reload_security(monkeypatch, host="127.0.0.1", token=None):
    monkeypatch.setenv("SWARM_HOST", host)
    if token is None:
        monkeypatch.delenv("SWARM_AUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SWARM_AUTH_TOKEN", token)
    monkeypatch.delenv("SWARM_ALLOW_PRIVATE_FETCH", raising=False)
    import app.config as cfg
    import app.security as sec
    importlib.reload(cfg)
    return importlib.reload(sec)


def test_loopback_no_token_allows(monkeypatch):
    sec = _reload_security(monkeypatch, host="127.0.0.1", token=None)
    assert sec._token_ok(None) is True


def test_exposed_no_token_blocks(monkeypatch):
    sec = _reload_security(monkeypatch, host="0.0.0.0", token=None)
    assert sec._token_ok(None) is False


def test_token_required_and_checked(monkeypatch):
    sec = _reload_security(monkeypatch, host="0.0.0.0", token="s3cret")
    assert sec._token_ok(None) is False
    assert sec._token_ok("wrong") is False
    assert sec._token_ok("s3cret") is True
    assert sec._token_ok("Bearer s3cret") is True


def test_ssrf_blocks_private_and_loopback(monkeypatch):
    sec = _reload_security(monkeypatch)
    assert sec.validate_outbound_url("http://127.0.0.1/x") is not None
    assert sec.validate_outbound_url("http://10.0.0.5/x") is not None
    assert sec.validate_outbound_url("http://169.254.169.254/latest/meta-data") is not None
    assert sec.validate_outbound_url("ftp://example.com") is not None


def test_ssrf_can_be_opted_out(monkeypatch):
    monkeypatch.setenv("SWARM_ALLOW_PRIVATE_FETCH", "1")
    import app.config as cfg
    import app.security as sec
    importlib.reload(cfg)
    importlib.reload(sec)
    assert sec.validate_outbound_url("http://127.0.0.1/x") is None


def test_blocked_commands(monkeypatch):
    sec = _reload_security(monkeypatch)
    assert sec.blocked_command("rm -rf /") is not None
    assert sec.blocked_command("git push --force origin main") is not None
    assert sec.blocked_command("shutdown now") is not None
    assert sec.blocked_command("ls -la") is None
    assert sec.blocked_command("python -m pytest") is None
