"""Static contract tests derived from the Hermes plugin SDKs, not from this repo."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_manifest_declares_a_complete_entrypoint() -> None:
    manifest = json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "llm-quota"
    assert manifest["version"] == "1.2.0"
    assert manifest["tab"]["path"] == "/llm-quota"
    assert manifest["entry"] == "dist/index.js"
    assert manifest["api"] == "plugin_api.py"
    assert (ROOT / "dashboard" / manifest["entry"]).is_file()
    assert (ROOT / "dashboard" / manifest["api"]).is_file()


def test_dashboard_entry_uses_the_official_web_plugin_registration() -> None:
    entry = (ROOT / "dashboard" / "dist" / "index.js").read_text(encoding="utf-8")

    assert entry.startswith("(function ()")
    assert "window.__HERMES_PLUGIN_SDK__" in entry
    assert 'window.__HERMES_PLUGINS__.register("llm-quota"' in entry
    assert "SDK.fetchJSON" in entry
    assert "window.hermesDesktop.api" not in entry


def test_desktop_plugin_uses_the_canonical_disk_contract() -> None:
    plugin_path = ROOT / "desktop" / "llm-quota" / "plugin.js"
    plugin = plugin_path.read_text(encoding="utf-8")

    assert plugin_path.is_file()
    assert "from '@hermes/plugin-sdk'" in plugin
    assert "from 'react/jsx-runtime'" in plugin
    assert "export default" in plugin
    assert "const ID = 'llm-quota'" in plugin
    assert "id: ID" in plugin
    assert "ctx.rest(path)" in plugin
    assert "window.hermesDesktop.api" not in plugin
    assert "llm-quota-monitor" not in plugin
    assert "StatusDot, { tone }" in plugin
    assert "ROUTES_AREA" in plugin
    assert "SIDEBAR_NAV_AREA" in plugin


def test_python_entrypoint_has_no_desktop_copy_side_effect() -> None:
    entrypoint = (ROOT / "__init__.py").read_text(encoding="utf-8")

    assert "def register(ctx)" in entrypoint
    assert "shutil" not in entrypoint
    assert "copy2" not in entrypoint
    assert "copytree" not in entrypoint
    assert not (ROOT / "desktop" / "plugin.js").exists()
    assert not (ROOT / "desktop" / "llm-quota-monitor").exists()


def test_versions_are_consistent() -> None:
    manifest = json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))
    plugin_yaml = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))

    assert plugin_yaml["name"] == manifest["name"]
    assert str(plugin_yaml["version"]) == manifest["version"]
