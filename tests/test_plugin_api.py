"""Unit tests for llm-quota helpers. No live provider calls."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

import plugin_api as api  # noqa: E402


def test_normalize_epoch_seconds_ms_and_s():
    assert api._normalize_epoch_seconds(1_700_000_000) == 1_700_000_000
    assert api._normalize_epoch_seconds(1_700_000_000_000) == 1_700_000_000
    assert api._normalize_epoch_seconds(None) is None
    assert api._normalize_epoch_seconds("nope") is None


def test_seconds_until_non_negative():
    past = time.time() - 3600
    assert api._seconds_until(past) == 0
    future = time.time() + 90
    remaining = api._seconds_until(future)
    assert remaining is not None and 80 <= remaining <= 90


def test_safe_error_redacts_bearer_and_http_status():
    class FakeResp:
        status_code = 429

    err = httpx.HTTPStatusError("boom", request=httpx.Request("GET", "https://x"), response=FakeResp())
    assert api._safe_error(err) == "HTTP 429"
    assert "[redacted]" in api._safe_error(RuntimeError("Bearer secret-token-value failed"))
    assert "secret-token-value" not in api._safe_error(RuntimeError("Bearer secret-token-value failed"))


def test_provider_token_from_store_reads_pool(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({
        "providers": {},
        "credential_pool": {
            "openai-codex": [{"access_token": "pool-token"}],
        },
    }), encoding="utf-8")
    assert api._provider_token_from_store(path, "openai-codex") == "pool-token"


def test_provider_token_prefers_singleton(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({
        "providers": {"openai-codex": {"tokens": {"access_token": "single"}}},
        "credential_pool": {"openai-codex": [{"access_token": "pool"}]},
    }), encoding="utf-8")
    assert api._provider_token_from_store(path, "openai-codex") == "single"


def test_jwt_account_id():
    payload = json.dumps({
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"},
    }).encode()
    b64 = __import__("base64").urlsafe_b64encode(payload).decode().rstrip("=")
    token = f"aaa.{b64}.sig"
    assert api._jwt_account_id(token) == "acct-1"
    assert api._jwt_account_id("not-a-jwt") == ""


def test_codex_rate_window_skips_null_percent():
    assert api._codex_rate_window({"used_percent": None}, kind="primary", label="Weekly") is None
    window = api._codex_rate_window(
        {"used_percent": 19, "limit_window_seconds": 604800, "reset_after_seconds": 10},
        kind="primary",
        label="Weekly",
    )
    assert window["percentage_remaining"] == 81
    assert window["label"] == "Weekly"


def test_openrouter_shape_is_windows():
    assert api._percentage_pair(40, None) == (40, 60)


def test_zai_success_requires_limits_via_fetch_contract():
    # Fail-closed: missing limits is an error payload, not empty-ok.
    assert api._zai_window_label("TIME_LIMIT", {"unit": 5, "number": 1}) == "Time / 1 day"
    assert api._zai_window_label("TOKENS_LIMIT", {"unit": 6, "number": 1}) == "Tokens / 1 weekly"


@pytest.mark.asyncio
async def test_get_all_quotas_survives_missing_keys(monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(api, "_resolve_codex_access_token", lambda: ("", ""))
    monkeypatch.setattr(api, "_resolve_grok_access_token", lambda: "")
    result = await api.get_all_quotas()
    assert result["providers"]["zai"]["status"] == "no_key"
    assert result["providers"]["openrouter"]["status"] == "no_key"
    assert result["providers"]["codex"]["status"] == "no_token"
    assert result["providers"]["grok"]["status"] == "no_token"
    assert "email" not in json.dumps(result)


# ---------------------------------------------------------------------------
# Regression tests: SSRF protection in _nous_portal_base_url
# ---------------------------------------------------------------------------

import hermes_cli.auth as core_auth


def test_nous_portal_base_url_rejects_poisoned_host(monkeypatch):
    """A poisoned portal_base_url must fall back to the default URL."""
    monkeypatch.setattr(
        core_auth, "get_provider_auth_state",
        lambda provider: {"portal_base_url": "https://attacker.invalid/base"},
    )
    result = api._nous_portal_base_url()
    assert result == "https://portal.nousresearch.com"
    assert "attacker.invalid" not in result


def test_nous_portal_base_url_accepts_valid_host(monkeypatch):
    """A valid portal host from the allowlist passes through."""
    monkeypatch.setattr(
        core_auth, "get_provider_auth_state",
        lambda provider: {"portal_base_url": "https://portal.nousresearch.com/some/path"},
    )
    result = api._nous_portal_base_url()
    assert result == "https://portal.nousresearch.com/some/path"


def test_nous_portal_base_url_accepts_loopback_http(monkeypatch):
    """Loopback http URLs are allowed for local dev/testing."""
    monkeypatch.setattr(
        core_auth, "get_provider_auth_state",
        lambda provider: {"portal_base_url": "http://127.0.0.1:8080/test"},
    )
    result = api._nous_portal_base_url()
    assert result == "http://127.0.0.1:8080/test"


def test_nous_portal_base_url_rejects_http_non_loopback(monkeypatch):
    """Plain http to a non-loopback host is rejected even if in allowlist."""
    monkeypatch.setattr(
        core_auth, "get_provider_auth_state",
        lambda provider: {"portal_base_url": "http://portal.nousresearch.com/"},
    )
    result = api._nous_portal_base_url()
    assert result == "https://portal.nousresearch.com"


# ---------------------------------------------------------------------------
# Regression tests: NaN/Infinity handling in _fetch_openrouter_credits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_nan_credits_does_not_crash():
    """NaN/Infinity from the API must not crash JSON serialization."""
    class FakeClient:
        async def get(self, url, **kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={"data": {"total_credits": "NaN", "total_usage": 1}},
            )
    result = await api._fetch_openrouter_credits(FakeClient(), "fake-key")
    serialized = json.dumps(result)  # must not raise ValueError
    assert result["status"] == "ok"
    w = result["windows"][0]
    # NaN should be sanitized to a finite value (0.0 after _safe_finite),
    # so limit equals itself (not NaN).
    assert w["limit"] == w["limit"]


@pytest.mark.asyncio
async def test_openrouter_infinity_usage_clamped():
    """Infinity usage must be clamped, not produce Infinity in the response."""
    class FakeClient:
        async def get(self, url, **kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={"data": {"total_credits": 10, "total_usage": "Infinity"}},
            )
    result = await api._fetch_openrouter_credits(FakeClient(), "fake-key")
    serialized = json.dumps(result)  # must not raise ValueError
    assert result["status"] == "ok"
    w = result["windows"][0]
    assert w["percentage_remaining"] >= 0
    assert w["percentage_used"] <= 100


@pytest.mark.asyncio
async def test_openrouter_overage_clamped_to_zero():
    """When usage > total, percentage_remaining must be clamped to 0 (not negative)."""
    class FakeClient:
        async def get(self, url, **kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={"data": {"total_credits": 10, "total_usage": 15}},
            )
    result = await api._fetch_openrouter_credits(FakeClient(), "fake-key")
    w = result["windows"][0]
    assert w["percentage_remaining"] == 0.0
    assert w["percentage_used"] == 100.0


# ---------------------------------------------------------------------------
# Regression tests: _safe_finite helper
# ---------------------------------------------------------------------------


def test_safe_finite_rejects_nan_inf():
    assert api._safe_finite("NaN") == 0.0
    assert api._safe_finite("Infinity") == 0.0
    assert api._safe_finite(None) == 0.0
    assert api._safe_finite(42) == 42.0
    assert api._safe_finite("3.14") == 3.14
