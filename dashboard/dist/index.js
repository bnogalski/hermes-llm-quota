(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) {
    console.error("llm-quota: window.__HERMES_PLUGIN_SDK__ is missing");
    return;
  }

  const React = SDK.React;
  const hooks = SDK.hooks;
  const C = SDK.components;
  const h = React.createElement;

  const API = "/api/plugins/llm-quota";
  const REFETCH_MS = 60000;
  const PROVIDER_ORDER = ["nous", "zai", "codex", "grok", "openrouter"];
  const PROVIDERS = {
    nous: "Nous Portal",
    zai: "Z.AI",
    codex: "Codex",
    grok: "Grok",
    openrouter: "OpenRouter",
  };
  const STATUS_LABEL = {
    ok: "OK",
    no_key: "No API key",
    no_token: "Not signed in",
    expired: "Session expired",
    forbidden: "Forbidden",
    error: "Error",
  };

  function remainingPct(item) {
    if (!item) return 100;
    if (item.percentage_remaining != null) return item.percentage_remaining;
    return 100 - (item.percentage_used || 0);
  }

  function fmtReset(seconds) {
    if (!seconds && seconds !== 0) return "-";
    if (seconds <= 0) return "now";
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (hrs > 24) return Math.floor(hrs / 24) + "d " + (hrs % 24) + "h";
    if (hrs > 0) return hrs + "h " + mins + "m";
    return mins + "m";
  }

  function fmtAmount(value) {
    if (value == null || value === "") return "-";
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    return Number.isInteger(n) ? String(n) : n.toFixed(1);
  }

  function barColor(pctRemaining) {
    if (pctRemaining <= 15) return "hsl(var(--destructive))";
    if (pctRemaining <= 40) return "hsl(var(--warning, 38 92% 50%))";
    return "hsl(var(--primary))";
  }

  function ProgressBar(props) {
    const pct = remainingPct(props.window);
    const used = Math.max(0, Math.min(100, 100 - pct));
    return h("div", { className: "flex items-center gap-2" },
      h("div", {
        className: "relative h-1.5 flex-1 overflow-hidden rounded-full bg-muted",
      }, h("div", {
        className: "absolute inset-y-0 left-0 rounded-full transition-all",
        style: { width: used + "%", backgroundColor: barColor(pct) },
      })),
      h("span", { className: "w-8 text-right text-xs tabular-nums text-muted-foreground" },
        Math.round(pct) + "%")
    );
  }

  function WindowRow(props) {
    const w = props.window;
    const usd = w.amount_unit === "USD";
    const hasCredits = w.remaining != null && w.limit != null;
    const amount = hasCredits
      ? (usd ? "$" : "") + fmtAmount(w.remaining) + " / " + (usd ? "$" : "") + fmtAmount(w.limit) +
        (w.amount_unit && !usd ? " " + w.amount_unit : "")
      : (w.reset_in_seconds != null ? "reset " + fmtReset(w.reset_in_seconds) : "");

    return h("div", { className: "flex flex-col gap-1" },
      h("div", { className: "flex items-center justify-between text-xs text-muted-foreground" },
        h("span", null, w.label || props.kind),
        h("span", { className: "tabular-nums" }, amount)
      ),
      h(ProgressBar, { window: w }),
      hasCredits && w.reset_in_seconds != null
        ? h("div", { className: "text-right text-[11px] tabular-nums text-muted-foreground" },
            "reset " + fmtReset(w.reset_in_seconds))
        : null
    );
  }

  function ProviderCard(props) {
    const data = props.data || {};
    const status = data.status || "error";
    const ok = status === "ok";
    const windows = ok && Array.isArray(data.windows) ? data.windows : [];

    return h(C.Card, null,
      h(C.CardHeader, { className: "pb-2" },
        h("div", { className: "flex items-center justify-between gap-2" },
          h(C.CardTitle, { className: "text-base" }, PROVIDERS[props.provider] || props.provider),
          h("div", { className: "flex items-center gap-1" },
            data.plan ? h(C.Badge, { variant: "outline" }, String(data.plan)) : null,
            h(C.Badge, { variant: ok ? "secondary" : "destructive" },
              STATUS_LABEL[status] || status)
          )
        )
      ),
      h(C.CardContent, { className: "flex flex-col gap-3" },
        ok
          ? windows.map(function (window, i) {
              return h(WindowRow, { key: props.provider + "-" + i, window: window });
            })
          : h("p", { className: "text-sm text-muted-foreground" },
              data.message || STATUS_LABEL[status] || status)
      )
    );
  }

  function QuotaPage() {
    const [payload, setPayload] = hooks.useState(null);
    const [error, setError] = hooks.useState(null);
    const [loading, setLoading] = hooks.useState(true);

    const load = hooks.useCallback(function () {
      return SDK.fetchJSON(API + "/all").then(function (data) {
        setPayload(data);
        setError(null);
      }).catch(function (err) {
        setError(err && err.message ? err.message : String(err));
      }).finally(function () {
        setLoading(false);
      });
    }, []);

    hooks.useEffect(function () {
      load();
      const id = setInterval(load, REFETCH_MS);
      return function () { clearInterval(id); };
    }, [load]);

    const providers = (payload && payload.providers) || {};
    const listed = PROVIDER_ORDER.filter(function (name) { return !!providers[name]; });

    return h("div", { className: "mx-auto flex max-w-3xl flex-col gap-4 p-6" },
      h("div", { className: "flex items-center justify-between" },
        h("div", null,
          h("h1", { className: "text-xl font-semibold" }, "LLM Quota Monitor"),
          h("p", { className: "text-sm text-muted-foreground" },
            "Z.AI, Codex, Grok, Nous Portal, and OpenRouter remaining allowance")
        ),
        h(C.Button, { variant: "outline", size: "sm", onClick: load }, "Refresh")
      ),
      loading && !payload
        ? h("p", { className: "text-sm text-muted-foreground" }, "Loading…")
        : null,
      error
        ? h("p", { className: "text-sm text-destructive" }, error)
        : null,
      !loading && !error && listed.length === 0
        ? h("p", { className: "text-sm text-muted-foreground" },
            "No providers returned by the backend")
        : listed.map(function (name) {
            return h(ProviderCard, { key: name, provider: name, data: providers[name] });
          }),
      payload && payload.timestamp
        ? h("p", { className: "text-xs text-muted-foreground" },
            "Updated " + new Date(payload.timestamp * 1000).toLocaleTimeString())
        : null
    );
  }

  window.__HERMES_PLUGINS__.register("llm-quota", QuotaPage);
})();
