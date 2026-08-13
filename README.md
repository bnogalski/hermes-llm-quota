# Hermes LLM Quota Monitor

Live token quota and usage monitor for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

Shows remaining allowance for:

- **Z.AI** coding plan (`ZAI_API_KEY` / `GLM_API_KEY`)
- **OpenAI Codex** (Hermes `openai-codex` auth store)
- **Grok** (Hermes `xai-oauth` auth store)
- **OpenRouter** credits (`OPENROUTER_API_KEY`)

The backend never returns secrets or account email. Error states (`no_key`, `no_token`, `expired`, `forbidden`, `error`) are shown in the pane instead of being hidden.

## Install

```bash
hermes plugins install bnogalski/hermes-llm-quota
hermes plugins enable llm-quota
```

`register()` copies `desktop/plugin.js` into `$HERMES_HOME/desktop-plugins/llm-quota/`. Reload desktop plugins (`Ctrl+K` → Reload desktop plugins) if the pane does not appear.

Manual copy (if you do not use `hermes plugins install`):

```bash
cp -r . ~/.hermes/plugins/llm-quota
cp desktop/plugin.js ~/.hermes/desktop-plugins/llm-quota/plugin.js
```

On Windows, `$HERMES_HOME` is typically `%LOCALAPPDATA%\hermes`.

## Requirements

- Hermes Agent with the desktop app (for the pane / status-bar chip)
- Provider credentials already configured in Hermes:
  - Z.AI / OpenRouter: env vars
  - Codex / Grok: `hermes auth` OAuth stores

The dashboard process must have the plugin in `plugins.enabled` or the Python API will not mount (`/api/plugins/llm-quota/all`).

## Layout

```
plugin.yaml                 # hermes plugins install manifest
__init__.py                 # copies the desktop pane on enable
dashboard/
  manifest.json             # dashboard tab + API mount
  plugin_api.py             # FastAPI router
desktop/
  plugin.js                 # Electron pane + status-bar chip
tests/
```

## Develop

```bash
python -m pytest tests -q
```

## License

MIT — Bartosz Nogalski
