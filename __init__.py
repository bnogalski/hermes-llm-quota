"""LLM Quota Monitor - optional Hermes Python plugin entrypoint.

The dashboard backend is discovered from dashboard/manifest.json and mounted
under /api/plugins/llm-quota. The desktop pane is a separate disk plugin under
$HERMES_HOME/desktop-plugins/llm-quota/plugin.js; Hermes does not copy desktop
assets from Python plugin register() hooks.
"""


def register(ctx) -> None:
    """Keep the native plugin entrypoint side-effect free."""
    del ctx
