"""LLM Quota Monitor - backend API routes.

Mounted at /api/plugins/llm-quota/ by the dashboard plugin system.

Queries quota/usage endpoints for Z.AI coding plan, OpenAI Codex (ChatGPT),
Grok OAuth subscription billing, and OpenRouter. Returns unified JSON consumed
by the desktop plugin UI.

No secrets or PII are logged or exposed - only usage percentages, plan labels,
and reset times.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter

log = logging.getLogger(__name__)
router = APIRouter()

_BEARER_RE = re.compile(r"(?i)(bearer\s+|token=)[^\s,;]+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_epoch_seconds(value: Any) -> int | None:
    """Coerce epoch ms or seconds to integer seconds."""
    if value is None or value == "":
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw > 10**11:
        raw = raw / 1000
    return int(raw)


def _epoch_ms_to_iso(epoch_ms: int | float | None) -> str | None:
    ts = _normalize_epoch_seconds(epoch_ms)
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _iso_to_epoch_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _normalize_epoch_seconds(value)
    if isinstance(value, str):
        numeric = _normalize_epoch_seconds(value) if value.replace(".", "", 1).isdigit() else None
        if numeric is not None:
            return numeric
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(parsed.timestamp())
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _seconds_until(value: Any) -> int | None:
    ts = _normalize_epoch_seconds(value)
    if ts is None:
        return None
    return max(0, int(ts - time.time()))


def _seconds_until_iso(value: Any) -> int | None:
    epoch = _iso_to_epoch_seconds(value)
    return _seconds_until(epoch) if epoch is not None else None


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    text = _BEARER_RE.sub(r"\1[redacted]", str(exc))
    return text[:200]


def _read_auth_store(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        log.warning("auth store is not valid JSON: %s", path.name)
        return {}
    except OSError as exc:
        log.warning("could not read auth store %s: %s", path.name, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _auth_store_paths(*, scan_all_profiles: bool) -> list[Path]:
    """Candidate Hermes auth stores, without exposing their contents.

    Named profile + global home first. Sibling-profile scan is only for the
    older-desktop case where HERMES_HOME is the global home and no profile
    env var is set.
    """
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    candidates: list[Path] = []
    profile_name = os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_ACTIVE_PROFILE")
    if profile_name:
        candidates.append(home / "profiles" / profile_name / "auth.json")
    candidates.append(home / "auth.json")
    if scan_all_profiles:
        profiles_dir = home / "profiles"
        if profiles_dir.is_dir():
            candidates.extend(sorted(profiles_dir.glob("*/auth.json")))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _provider_token_from_store(path: Path, provider: str) -> str:
    store = _read_auth_store(path)
    providers = store.get("providers") if isinstance(store, dict) else None
    state = providers.get(provider) if isinstance(providers, dict) else None
    tokens = state.get("tokens") if isinstance(state, dict) else None
    if isinstance(tokens, dict):
        token = str(tokens.get("access_token") or "").strip()
        if token:
            return token

    pool = store.get("credential_pool") if isinstance(store, dict) else None
    entries = pool.get(provider) if isinstance(pool, dict) else None
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                token = str(entry.get("access_token") or "").strip()
                if token:
                    return token
    return ""


def _codex_account_id_from_store(path: Path) -> str:
    store = _read_auth_store(path)
    providers = store.get("providers") if isinstance(store, dict) else None
    state = providers.get("openai-codex") if isinstance(providers, dict) else None
    tokens = state.get("tokens") if isinstance(state, dict) else None
    if isinstance(tokens, dict):
        account_id = str(tokens.get("account_id") or "").strip()
        if account_id:
            return account_id
    return ""


def _jwt_account_id(token: str) -> str:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return ""
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        auth = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else None
        if isinstance(auth, dict):
            return str(auth.get("chatgpt_account_id") or "").strip()
    except Exception:
        return ""
    return ""


def _resolve_store_token(provider: str, *, scan_all_profiles: bool) -> str:
    for path in _auth_store_paths(scan_all_profiles=scan_all_profiles):
        token = _provider_token_from_store(path, provider)
        if token:
            return token
    return ""


def _profile_env_set() -> bool:
    return bool(os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_ACTIVE_PROFILE"))


def _resolve_grok_access_token() -> str:
    """Resolve a usable Grok OAuth bearer without logging or returning it."""
    try:
        from hermes_cli.auth import resolve_xai_oauth_runtime_credentials

        credentials = resolve_xai_oauth_runtime_credentials(refresh_if_expiring=True)
        token = str(credentials.get("api_key") or "").strip()
        if token:
            return token
        return _resolve_store_token("xai-oauth", scan_all_profiles=False)
    except ImportError:
        return _resolve_store_token("xai-oauth", scan_all_profiles=not _profile_env_set())
    except Exception:
        return _resolve_store_token("xai-oauth", scan_all_profiles=False)


def _resolve_codex_access_token() -> tuple[str, str]:
    """Return (access_token, account_id) without logging either value."""
    try:
        from hermes_cli.auth import resolve_codex_runtime_credentials

        credentials = resolve_codex_runtime_credentials(refresh_if_expiring=True)
        token = str(credentials.get("api_key") or "").strip()
        if token:
            account_id = _jwt_account_id(token)
            if not account_id:
                for path in _auth_store_paths(scan_all_profiles=False):
                    account_id = _codex_account_id_from_store(path)
                    if account_id:
                        break
            return token, account_id
        token = _resolve_store_token("openai-codex", scan_all_profiles=False)
        return token, _jwt_account_id(token)
    except ImportError:
        token = _resolve_store_token("openai-codex", scan_all_profiles=not _profile_env_set())
        return token, _jwt_account_id(token)
    except Exception:
        token = _resolve_store_token("openai-codex", scan_all_profiles=False)
        return token, _jwt_account_id(token)


def _percentage_pair(used: float | None, remaining: float | None) -> tuple[float, float]:
    if remaining is not None:
        remaining = min(100, max(0, remaining))
        used_pct = 100 - remaining if used is None else min(100, max(0, used))
        return used_pct, remaining
    if used is None:
        return 0.0, 100.0
    used_pct = min(100, max(0, used))
    return used_pct, 100 - used_pct


def _grok_monthly_window(config: dict[str, Any]) -> dict[str, Any] | None:
    monthly_limit = config.get("monthlyLimit") or {}
    used_value = config.get("used") or {}
    limit_raw = _number(monthly_limit.get("val")) if isinstance(monthly_limit, dict) else None
    used_raw = _number(used_value.get("val")) if isinstance(used_value, dict) else None
    if limit_raw is None or limit_raw <= 0 or used_raw is None:
        return None

    # The billing endpoint reports these integer values in cents/100 units.
    limit = limit_raw / 100
    used = max(0, used_raw / 100)
    remaining = max(0, limit - used)
    used_pct = min(100, max(0, used / limit * 100))
    reset_at = config.get("billingPeriodEnd")
    return {
        "type": "monthly_extra",
        "label": "Monthly extra credits",
        "percentage_used": used_pct,
        "percentage_remaining": 100 - used_pct,
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "amount_unit": "credits",
        "reset_at": reset_at,
        "reset_in_seconds": _seconds_until_iso(reset_at),
    }


def _grok_weekly_window(config: dict[str, Any]) -> dict[str, Any] | None:
    used_pct = _number(config.get("creditUsagePercent"))
    if used_pct is None:
        return None
    # xAI returns this field in percentage units: 33.0 means 33%, not 0.33%.
    used_pct = min(100, max(0, used_pct))
    period = config.get("currentPeriod") or {}
    reset_at = period.get("end") or config.get("billingPeriodEnd")
    return {
        "type": "weekly",
        "label": "Weekly credits",
        "percentage_used": used_pct,
        "percentage_remaining": 100 - used_pct,
        "reset_at": reset_at,
        "reset_in_seconds": _seconds_until_iso(reset_at),
    }


def _codex_rate_window(raw: Any, *, kind: str, label: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    used_pct = _number(raw.get("used_percent"))
    if used_pct is None:
        return None
    used_pct, remaining = _percentage_pair(used_pct, None)
    return {
        "type": kind,
        "label": label,
        "percentage_used": used_pct,
        "percentage_remaining": remaining,
        "window_seconds": raw.get("limit_window_seconds"),
        "reset_in_seconds": raw.get("reset_after_seconds"),
    }


# ---------------------------------------------------------------------------
# xAI / Grok OAuth billing
# ---------------------------------------------------------------------------

async def _fetch_grok_usage(client: httpx.AsyncClient) -> dict[str, Any]:
    """Fetch Grok subscription quota from xAI's billing proxy.

    The subscription endpoint is separate from the xAI API-key rate-limit
    surface. ``format=credits`` is the current weekly shared-credit window;
    the plain endpoint exposes the monthly extra-credit envelope.
    """
    access_token = await asyncio.to_thread(_resolve_grok_access_token)
    if not access_token:
        return {"provider": "grok", "status": "no_token"}

    url = "https://cli-chat-proxy.grok.com/v1/billing"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "xai-grok-cli",
        "X-Xai-Token-Auth": "xai-grok-cli",
        "x-grok-client-identifier": "grok-cli",
        "x-grok-client-version": "0.2.103",
    }
    try:
        weekly_resp, monthly_resp = await asyncio.gather(
            client.get(url, params={"format": "credits"}, headers=headers, timeout=15),
            client.get(url, headers=headers, timeout=15),
        )
        responses = (weekly_resp, monthly_resp)
        if all(resp.status_code == 401 for resp in responses):
            return {"provider": "grok", "status": "expired"}
        if all(resp.status_code == 403 for resp in responses):
            return {"provider": "grok", "status": "forbidden"}

        windows: list[dict[str, Any]] = []
        errors: list[str] = []
        for kind, resp in (("weekly", weekly_resp), ("monthly", monthly_resp)):
            if resp.status_code in (401, 403):
                errors.append(f"{kind} HTTP {resp.status_code}")
                continue
            try:
                resp.raise_for_status()
                payload = resp.json()
                config = payload.get("config") if isinstance(payload, dict) else None
                if not isinstance(config, dict):
                    errors.append(f"{kind} missing config")
                    continue
                window = _grok_weekly_window(config) if kind == "weekly" else _grok_monthly_window(config)
                if window:
                    windows.append(window)
                else:
                    errors.append(f"{kind} missing usage fields")
            except Exception as exc:
                errors.append(f"{kind}: {_safe_error(exc)}")

        if not windows:
            return {"provider": "grok", "status": "error", "message": "; ".join(errors) or "no quota data"}

        limit_reached = any(w.get("percentage_remaining", 100) <= 0 for w in windows)
        result: dict[str, Any] = {
            "provider": "grok",
            "status": "ok",
            "plan": "xAI OAuth",
            "allowed": not limit_reached,
            "limit_reached": limit_reached,
            "windows": windows,
        }
        if errors:
            result["partial"] = True
        return result
    except Exception as exc:
        return {"provider": "grok", "status": "error", "message": _safe_error(exc)}


# ---------------------------------------------------------------------------
# Z.AI coding plan quota
# ---------------------------------------------------------------------------

def _zai_window_label(ltype: str, lim: dict) -> str:
    if ltype == "TIME_LIMIT":
        unit_map = {3: "min", 4: "hour", 5: "day", 6: "week"}
        unit = unit_map.get(lim.get("unit", 0), f"unit-{lim.get('unit')}")
        return f"Time / {lim.get('number', '?')} {unit}"
    if ltype == "TOKENS_LIMIT":
        unit_map = {3: "5h rolling", 6: "weekly"}
        unit = unit_map.get(lim.get("unit", 0), f"unit-{lim.get('unit')}")
        return f"Tokens / {lim.get('number', '?')} {unit}"
    return ltype


async def _fetch_zai_quota(client: httpx.AsyncClient, api_key: str) -> dict[str, Any]:
    """Fetch Z.AI coding plan usage from the monitoring endpoint."""
    url = "https://api.z.ai/api/monitor/usage/quota/limit"
    try:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        success = data.get("success")
        code = data.get("code")
        if success is not True and code != 200:
            return {"provider": "zai", "status": "error", "message": str(data.get("msg") or "unknown")[:200]}

        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        limits = payload.get("limits")
        if not isinstance(limits, list):
            return {"provider": "zai", "status": "error", "message": "missing limits"}

        windows = []
        for lim in limits:
            if not isinstance(lim, dict):
                continue
            ltype = lim.get("type", "")
            pct = _number(lim.get("percentage")) or 0
            used_pct, remaining = _percentage_pair(pct, None)
            reset_ms = lim.get("nextResetTime")
            windows.append({
                "type": ltype,
                "label": _zai_window_label(str(ltype), lim),
                "percentage_used": used_pct,
                "percentage_remaining": remaining,
                "reset_at": _epoch_ms_to_iso(reset_ms),
                "reset_in_seconds": _seconds_until(reset_ms),
                "usage": lim.get("usage"),
                "current_value": lim.get("currentValue"),
                "remaining": lim.get("remaining"),
            })

        return {
            "provider": "zai",
            "status": "ok",
            "plan": payload.get("level", "unknown"),
            "windows": windows,
        }
    except Exception as exc:
        return {"provider": "zai", "status": "error", "message": _safe_error(exc)}


# ---------------------------------------------------------------------------
# OpenAI Codex / ChatGPT usage
# ---------------------------------------------------------------------------

async def _fetch_codex_usage(client: httpx.AsyncClient) -> dict[str, Any]:
    """Fetch Codex usage from ChatGPT backend API."""
    try:
        access_token, account_id = await asyncio.to_thread(_resolve_codex_access_token)
    except Exception as exc:
        return {"provider": "codex", "status": "error", "message": _safe_error(exc)}

    if not access_token:
        return {"provider": "codex", "status": "no_token"}

    url = "https://chatgpt.com/backend-api/wham/usage"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "User-Agent": "Mozilla/5.0",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    try:
        resp = await client.get(url, headers=headers, timeout=15)
        if resp.status_code == 401:
            return {"provider": "codex", "status": "expired"}
        if resp.status_code == 403:
            return {"provider": "codex", "status": "forbidden"}
        resp.raise_for_status()
        payload = resp.json()
        data = payload if isinstance(payload, dict) else {}

        plan = data.get("plan_type", "unknown")
        rl = data.get("rate_limit") or {}
        if not isinstance(rl, dict):
            rl = {}
        allowed = rl.get("allowed", True)
        limit_reached = rl.get("limit_reached", False)

        spend_control = data.get("spend_control") or {}
        if not isinstance(spend_control, dict):
            spend_control = {}
        individual_limit = spend_control.get("individual_limit") or {}

        windows = []
        primary = rl.get("primary_window")
        if isinstance(primary, dict):
            window_s = _number(primary.get("limit_window_seconds")) or 0
            label = "Weekly" if window_s >= 86400 else "Primary"
            window = _codex_rate_window(primary, kind="primary", label=label)
            if window:
                windows.append(window)
        secondary = rl.get("secondary_window")
        if isinstance(secondary, dict):
            window_s = _number(secondary.get("limit_window_seconds")) or 0
            label = "5h rolling" if window_s and window_s <= 36000 else "Secondary"
            window = _codex_rate_window(secondary, kind="secondary", label=label)
            if window:
                windows.append(window)
        if isinstance(individual_limit, dict) and individual_limit:
            used_pct, remaining = _percentage_pair(
                _number(individual_limit.get("used_percent")),
                _number(individual_limit.get("remaining_percent")),
            )
            windows.append({
                "type": "individual_allowance",
                "label": "Credits",
                "limit": individual_limit.get("limit"),
                "used": individual_limit.get("used"),
                "remaining": individual_limit.get("remaining"),
                "percentage_used": used_pct,
                "percentage_remaining": remaining,
                "reset_in_seconds": individual_limit.get("reset_after_seconds"),
                "reset_at": individual_limit.get("reset_at"),
            })

        return {
            "provider": "codex",
            "status": "ok",
            "plan": plan,
            "allowed": allowed,
            "limit_reached": limit_reached,
            "windows": windows,
        }
    except Exception as exc:
        return {"provider": "codex", "status": "error", "message": _safe_error(exc)}


# ---------------------------------------------------------------------------
# Nous Portal (Nous Research) credits
# ---------------------------------------------------------------------------

def _resolve_nous_access_token() -> str:
    """Resolve a usable Nous Portal OAuth bearer (auto-refresh, like Grok)."""
    try:
        from hermes_cli.auth import resolve_nous_access_token

        token = resolve_nous_access_token()
        return str(token).strip() if token else ""
    except ImportError:
        return _resolve_store_token("nous", scan_all_profiles=not _profile_env_set())
    except Exception:
        return ""


def _nous_portal_base_url() -> str:
    """Return the portal base URL from auth state (fallback: default)."""
    try:
        from hermes_cli.auth import get_provider_auth_state

        state = get_provider_auth_state("nous") or {}
        url = state.get("portal_base_url")
        return url.strip() if isinstance(url, str) and url.strip() else "https://portal.nousresearch.com"
    except Exception:
        return "https://portal.nousresearch.com"


async def _fetch_nous_credits(client: httpx.AsyncClient) -> dict[str, Any]:
    """Fetch Nous Portal credit balance and subscription state."""
    access_token = await asyncio.to_thread(_resolve_nous_access_token)
    if not access_token:
        return {"provider": "nous", "status": "no_token"}

    base = _nous_portal_base_url()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    windows: list[dict[str, Any]] = []
    errors: list[str] = []
    balance: float | None = None
    total_credits: float | None = None
    sub_credits: float | None = None
    purch_credits: float | None = None
    plan_label = "unknown"
    tier_name: str | None = None

    try:
        billing_resp, account_resp = await asyncio.gather(
            client.get(f"{base}/api/billing/state", headers=headers, timeout=10),
            client.get(f"{base}/api/oauth/account", headers=headers, timeout=10),
        )

        if billing_resp.status_code == 401 or account_resp.status_code == 401:
            return {"provider": "nous", "status": "expired"}
        if billing_resp.status_code == 403 and account_resp.status_code == 403:
            return {"provider": "nous", "status": "forbidden"}

        # --- billing/state ---
        if billing_resp.status_code == 200:
            billing = billing_resp.json()
            if isinstance(billing, dict):
                balance = _number(billing.get("balanceUsd"))
        else:
            errors.append(f"billing/state HTTP {billing_resp.status_code}")

        # --- oauth/account ---
        if account_resp.status_code == 200:
            account = account_resp.json()
            if isinstance(account, dict):
                total_credits = _number(account.get("total_usable_credits"))
                sub_credits = _number(account.get("subscription_credits_remaining"))
                purch_credits = _number(account.get("purchased_credits_remaining"))
                has_sub = account.get("has_active_subscription")
                sub_tier = account.get("subscription_tier")
                paid_access = account.get("paid_service_access")
                if isinstance(paid_access, dict):
                    paid_access = paid_access.get("allowed")

                # Resolve human-readable tier name
                tiers_raw = account.get("tiers")
                if has_sub and isinstance(tiers_raw, list):
                    for t in tiers_raw:
                        if isinstance(t, dict) and t.get("tier") == sub_tier:
                            tier_name = t.get("name")
                            break

                plan_parts: list[str] = []
                if tier_name:
                    plan_parts.append(tier_name)
                elif has_sub and sub_tier:
                    plan_parts.append(f"tier {sub_tier}")
                if paid_access:
                    plan_parts.append("paid")
                plan_label = ", ".join(plan_parts) if plan_parts else ("Subscription" if has_sub else "Free")
        else:
            errors.append(f"oauth/account HTTP {account_resp.status_code}")

        # --- Build windows ---
        # Primary: total usable credits (subscription + purchased combined)
        if total_credits is not None and total_credits > 0:
            # total_usable_credits is the remaining balance; we don't know the
            # original grant, so show remaining with a flat bar
            windows.append({
                "type": "credits",
                "label": "Credits",
                "remaining": total_credits,
                "limit": total_credits,
                "used": 0,
                "percentage_remaining": 100,
                "percentage_used": 0,
                "amount_unit": "USD",
            })
            # Show subscription vs purchased breakdown if both present
            if sub_credits and sub_credits > 0:
                windows.append({
                    "type": "subscription_credits",
                    "label": "  subscription",
                    "remaining": sub_credits,
                    "amount_unit": "USD",
                })
            if purch_credits and purch_credits > 0:
                windows.append({
                    "type": "purchased_credits",
                    "label": "  purchased",
                    "remaining": purch_credits,
                    "amount_unit": "USD",
                })
        elif balance is not None and balance > 0:
            # Fallback: purchased balance only
            windows.append({
                "type": "balance",
                "label": "Balance",
                "remaining": balance,
                "limit": balance,
                "used": 0,
                "percentage_remaining": 100,
                "percentage_used": 0,
                "amount_unit": "USD",
            })
        else:
            # No credits at all — show $0 so the user knows
            windows.append({
                "type": "balance",
                "label": "Balance",
                "remaining": 0,
                "limit": 0,
                "used": 0,
                "percentage_remaining": 0,
                "percentage_used": 100,
                "amount_unit": "USD",
            })

        result: dict[str, Any] = {
            "provider": "nous",
            "status": "ok",
            "plan": plan_label,
            "windows": windows,
        }
        if errors:
            result["partial"] = True
        return result
    except Exception as exc:
        return {"provider": "nous", "status": "error", "message": _safe_error(exc)}


# ---------------------------------------------------------------------------
# OpenRouter credits
# ---------------------------------------------------------------------------

async def _fetch_openrouter_credits(client: httpx.AsyncClient, api_key: str) -> dict[str, Any]:
    """Fetch OpenRouter credit balance."""
    url = "https://openrouter.ai/api/v1/credits"
    try:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        payload = payload if isinstance(payload, dict) else {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        total = float(data.get("total_credits", 0) or 0)
        usage = float(data.get("total_usage", 0) or 0)
        remaining = round(total - usage, 2)
        remaining_pct = round((remaining / total) * 100, 1) if total > 0 else 0.0
        return {
            "provider": "openrouter",
            "status": "ok",
            "windows": [{
                "type": "credits",
                "label": "Credits",
                "limit": total,
                "used": usage,
                "remaining": remaining,
                "percentage_used": round(100 - remaining_pct, 1) if total > 0 else 0.0,
                "percentage_remaining": remaining_pct,
                "amount_unit": "USD",
            }],
        }
    except Exception as exc:
        return {"provider": "openrouter", "status": "error", "message": _safe_error(exc)}


# ---------------------------------------------------------------------------
# Unified endpoint
# ---------------------------------------------------------------------------

async def _no_key_result(name: str) -> dict[str, Any]:
    return {"provider": name, "status": "no_key"}


@router.get("/all")
async def get_all_quotas() -> dict[str, Any]:
    """Fetch quota/usage from all configured providers in parallel."""
    zai_key = os.environ.get("ZAI_API_KEY") or os.environ.get("GLM_API_KEY") or ""
    or_key = os.environ.get("OPENROUTER_API_KEY") or ""

    async with httpx.AsyncClient() as client:
        tasks: list[tuple[str, Any]] = []
        if zai_key:
            tasks.append(("zai", _fetch_zai_quota(client, zai_key)))
        else:
            tasks.append(("zai", _no_key_result("zai")))
        tasks.append(("codex", _fetch_codex_usage(client)))
        tasks.append(("grok", _fetch_grok_usage(client)))
        tasks.append(("nous", _fetch_nous_credits(client)))
        if or_key:
            tasks.append(("openrouter", _fetch_openrouter_credits(client, or_key)))
        else:
            tasks.append(("openrouter", _no_key_result("openrouter")))

        results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

    provider_data: dict[str, Any] = {}
    for (name, _), result in zip(tasks, results):
        if isinstance(result, BaseException):
            provider_data[name] = {"provider": name, "status": "error", "message": _safe_error(result)}
        else:
            provider_data[name] = result

    summary = ", ".join(
        f"{n}={d.get('status', '?')}" for n, d in provider_data.items()
    )
    log.info("llm-quota /all response: %s", summary)

    return {
        "timestamp": time.time(),
        "providers": provider_data,
    }


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "plugin": "llm-quota"}
