"""Phase 0: CLI output must never leak secrets (Codex High finding)."""

from jobpilot.cli import _redact, _redact_url


def test_redact_url_masks_credentials():
    out = _redact_url("postgresql+psycopg://admin:s3cr3t@db.internal:5432/prod")
    assert "s3cr3t" not in out
    assert "admin" not in out
    assert "***:***@db.internal:5432" in out
    assert out.startswith("postgresql+psycopg://")


def test_redact_url_no_credentials_is_unchanged():
    url = "postgresql+psycopg://localhost:5432/jobpilot"
    assert _redact_url(url) == url


def test_redact_url_empty():
    assert _redact_url("") == "(empty)"


def test_redact_token_hides_value():
    assert "supersecrettoken" not in _redact("supersecrettoken")
    assert _redact("") == "(empty)"


def test_config_command_output_has_no_password(capsys):
    from jobpilot.cli import cmd_config

    cmd_config(None)  # type: ignore[arg-type]
    captured = capsys.readouterr().out
    # Default config has no secrets set, but the printed DB URL must be masked
    # if credentials are ever present. Assert the raw default creds are shown
    # only via the masked form (jobpilot:jobpilot must not appear verbatim).
    assert "jobpilot:jobpilot@" not in captured
