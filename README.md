# Hermes LLM Quota Monitor

A standalone plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
It shows live quota and usage for the providers configured on the Hermes host:

- **Z.AI** coding plan via `ZAI_API_KEY` or `GLM_API_KEY`
- **OpenAI Codex** via the Hermes `openai-codex` auth store
- **Grok** via the Hermes `xai-oauth` auth store
- **OpenRouter** credits via `OPENROUTER_API_KEY`

The backend returns no secrets or account email. Provider failures remain visible
as explicit states: `no_key`, `no_token`, `expired`, `forbidden`, or `error`.

## Installation

The web dashboard plugin and the native desktop plugin are separate Hermes
extension surfaces. They share one backend namespace: `/api/plugins/llm-quota/`.

### Backend and web dashboard

```bash
hermes plugins install bnogalski/hermes-llm-quota
hermes plugins enable llm-quota
```

The API is mounted at `/api/plugins/llm-quota/`. Restart the dashboard or gateway
process when the installed plugin is not picked up. The backend must be enabled
in `plugins.enabled` for its API routes to mount.

### Native desktop pane

From the repository root, copy the canonical disk plugin file without renaming
its directory or id:

```bash
mkdir -p "$HERMES_HOME/desktop-plugins/llm-quota"
cp desktop/llm-quota/plugin.js "$HERMES_HOME/desktop-plugins/llm-quota/plugin.js"
```

On Windows, use the equivalent `%HERMES_HOME%\\desktop-plugins\\llm-quota\\plugin.js`
path. If `HERMES_HOME` is not set, Hermes normally uses the profile home under
`%LOCALAPPDATA%\\hermes`.

Reload desktop plugins from the desktop command palette. The plugin registers a
right-side quota pane, a status-bar chip, a desktop route, and sidebar navigation.
The desktop ID is `llm-quota`, matching the backend namespace, so `ctx.rest('/all')`
is the official scoped API door.

## Requirements

- Hermes Agent with the web dashboard for the backend and dashboard tab
- Hermes Desktop for the native pane and status-bar chip
- Credentials configured for at least one provider
- The dashboard plugin enabled in Hermes configuration

## Layout

```text
plugin.yaml
__init__.py                       # side-effect-free Python entrypoint
dashboard/
  manifest.json                   # dashboard tab and backend declaration
  dist/index.js                   # official dashboard IIFE entry
  plugin_api.py                   # FastAPI router
desktop/
  llm-quota/plugin.js             # native desktop disk plugin
tests/
```

The Python entrypoint does not copy files into another Hermes directory. Hermes
loads the dashboard backend from its manifest, while the desktop app loads the
ESM file from `desktop-plugins/llm-quota/`.

## Development

```bash
python -m pytest tests -q
```

The tests do not call provider APIs. Validate the two JavaScript entry files with
Acorn before distributing a change:

```bash
node -e "const fs=require('fs'), acorn=require('acorn'); for (const f of ['dashboard/dist/index.js','desktop/llm-quota/plugin.js']) acorn.parse(fs.readFileSync(f,'utf8'), {ecmaVersion:2022, sourceType: f.includes('/desktop/') ? 'module' : 'script'}); console.log('JS syntax OK')"
```

## Support

If this plugin saved you some time, a tip is always appreciated.

**BTC (Bech32):**

```
bc1q4refcfue5dvatkx96e3xv7xr6pde24u20nvjfv
```

## License

MIT, Copyright (c) 2026 Bartosz Nogalski
