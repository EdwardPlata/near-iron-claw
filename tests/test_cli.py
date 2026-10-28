"""Tests for the CLI entry point, driving it in-process with a mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from near_iron_claw import NearAIClient, Settings
from near_iron_claw import cli as cli_mod
from testkit import MODELS_BODY, REAL_KEY, chat_response


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Prevent the real ./.env or ambient env from leaking into CLI tests."""
    for var in (
        "LLM_API_KEY", "OPENAI_API_KEY", "NEAR_AI_API_KEY",
        "LLM_BASE_URL", "OPENAI_BASE_URL", "LLM_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    # Disable reading the real ./.env file so tests are hermetic.
    monkeypatch.setattr("dotenv.dotenv_values", lambda *a, **k: {})


def patch_transport(monkeypatch, handler, *, key=REAL_KEY):
    """Force cli.NearAIClient(...) to use our mock transport and a fixed key."""
    original = cli_mod.NearAIClient

    def factory(settings, **kwargs):
        s = Settings(
            base_url=settings.base_url,
            api_key=key if key is not None else settings.api_key,
            model=settings.model,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )
        return original(s, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(cli_mod, "NearAIClient", factory)


def test_config_redacts_key(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", REAL_KEY)
    rc = cli_mod.main(["config"])
    out = capsys.readouterr().out
    assert rc == 0
    assert REAL_KEY not in out
    assert "sk-agent-" in out  # redacted prefix still shown
    assert "has_valid_key" in out


def test_config_json(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", REAL_KEY)
    rc = cli_mod.main(["--json", "config"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["has_valid_key"] is True
    assert REAL_KEY not in json.dumps(payload)


def test_models_command(monkeypatch, capsys):
    patch_transport(monkeypatch, lambda r: httpx.Response(200, json=MODELS_BODY))
    rc = cli_mod.main(["models"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "openai/gpt-5.5" in out
    assert "anthropic/claude-opus-4-7" in out


def test_chat_command(monkeypatch, capsys):
    def handler(request):
        return httpx.Response(200, json=chat_response("hello!"))

    patch_transport(monkeypatch, handler)
    rc = cli_mod.main(["chat", "say hi"])
    assert rc == 0
    assert "hello!" in capsys.readouterr().out


def test_chat_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("piped prompt"))

    def handler(request):
        assert "piped prompt" in request.read().decode()
        return httpx.Response(200, json=chat_response("ok"))

    patch_transport(monkeypatch, handler)
    assert cli_mod.main(["chat"]) == 0


def test_chat_empty_prompt_errors(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("   "))
    patch_transport(monkeypatch, lambda r: httpx.Response(200, json={}))
    rc = cli_mod.main(["chat"])
    assert rc == 2
    assert "no prompt" in capsys.readouterr().err


def test_verify_command_success(monkeypatch, capsys):
    def handler(request):
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json=chat_response("pong"))
        return httpx.Response(200, json=MODELS_BODY)

    patch_transport(monkeypatch, handler)
    rc = cli_mod.main(["verify"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "gateway reachable: True" in out
    assert "key valid: True" in out


def test_verify_command_bad_key_exit_code(monkeypatch, capsys):
    def handler(request):
        if request.headers.get("authorization"):
            return httpx.Response(401, text="nope")
        return httpx.Response(200, json=MODELS_BODY)

    patch_transport(monkeypatch, handler)
    rc = cli_mod.main(["verify"])
    assert rc == 1  # non-zero on failure


def test_missing_key_config_error(monkeypatch, capsys):
    # No key set anywhere -> models command should surface a ConfigError, rc=2.
    monkeypatch.setattr(
        cli_mod, "NearAIClient",
        lambda settings, **kw: NearAIClient(
            settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=MODELS_BODY))
        ),
    )
    rc = cli_mod.main(["chat", "hi"])
    assert rc == 2
    assert "config error" in capsys.readouterr().err.lower()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--version"])
    assert exc.value.code == 0
    assert "near-iron-claw" in capsys.readouterr().out


def test_stream_and_json_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--json", "chat", "hi", "--stream"])
    assert exc.value.code == 2
    assert "--stream cannot be combined with --json" in capsys.readouterr().err


def test_missing_env_file_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["--env-file", "/no/such/file.env", "config"])
    assert exc.value.code == 2
    assert "--env-file not found" in capsys.readouterr().err
