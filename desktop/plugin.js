/**
 * LLM Quota Monitor — desktop pane showing live token quota for Z.AI,
 * OpenAI Codex, Grok, and OpenRouter.
 *
 * Backend: dashboard/plugin_api.py → ctx.rest('/all')
 * Mounted at /api/plugins/llm-quota/ by the dashboard.
 */

import {
  cn, haptic, host,
  useQuery,
  ScrollArea, GlyphSpinner, ErrorState,
  StatusDot, Badge, Button, Tip, Codicon,
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'llm-quota'
const REFETCH_MS = 60_000
const PROVIDERS = {
  zai: { label: 'Z.AI', icon: 'spark', chip: 'ZAI' },
  codex: { label: 'Codex', icon: 'copilot', chip: 'CDX' },
  grok: { label: 'Grok', icon: 'spark', chip: 'GRK' },
  openrouter: { label: 'OpenRouter', icon: 'route', chip: 'OR' },
}
const PROVIDER_ORDER = Object.keys(PROVIDERS)
const STATUS_LABEL = {
  ok: 'OK',
  no_key: 'No API key',
  no_token: 'Not signed in',
  expired: 'Session expired',
  forbidden: 'Forbidden',
  error: 'Error',
}

let _ctx = null

function remainingPct(item) {
  if (!item) return 100
  if (item.percentage_remaining != null) return item.percentage_remaining
  return 100 - (item.percentage_used || 0)
}

function statusOf(data) {
  return (data && data.status) || 'error'
}

function isOk(data) {
  return statusOf(data) === 'ok'
}

function useQuota() {
  return useQuery({
    queryKey: [ID, 'all'],
    queryFn: () => _ctx.rest('/all'),
    refetchInterval: REFETCH_MS,
    staleTime: 30_000,
  })
}

function fmtReset(seconds) {
  if (!seconds && seconds !== 0) return '-'
  if (seconds <= 0) return 'now'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 24) return Math.floor(h / 24) + 'd ' + (h % 24) + 'h'
  if (h > 0) return h + 'h ' + m + 'm'
  return m + 'm'
}

function fmtTime(unixTs) {
  if (!unixTs) return '-'
  var d = new Date(unixTs * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function fmtCreditAmount(value) {
  if (value == null || value === '') return '-'
  var n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function pctColor(pctRemaining) {
  if (pctRemaining <= 15) return 'var(--ui-danger, #ef4444)'
  if (pctRemaining <= 40) return 'var(--ui-warning, #f59e0b)'
  return 'var(--ui-success, #22c55e)'
}

function ProgressBar({ pctRemaining }) {
  var used = 100 - pctRemaining
  var color = pctColor(pctRemaining)
  return jsxs('div', {
    className: 'flex items-center gap-2',
    children: [
      jsx('div', {
        className: 'relative h-1.5 flex-1 overflow-hidden rounded-full',
        style: { backgroundColor: 'var(--ui-stroke-secondary, #333)' },
        children: jsx('div', {
          className: 'absolute inset-y-0 left-0 rounded-full transition-all duration-500',
          style: { width: used + '%', backgroundColor: color },
        }),
      }),
      jsx('span', {
        className: 'text-[0.625rem] font-medium tabular-nums w-7 text-right',
        style: { color: color },
        children: Math.round(pctRemaining) + '%',
      }),
    ],
  })
}

function WindowRow({ provider, window, index }) {
  return jsxs('div', {
    className: 'flex flex-col gap-0.5',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between text-[0.625rem]',
        style: { color: 'var(--ui-text-tertiary, #888)' },
        children: [
          jsx('span', { children: window.label }),
          window.remaining != null && window.limit != null
            ? jsxs('span', {
              className: 'tabular-nums',
              children: [
                window.amount_unit === 'USD' ? '$' : '',
                fmtCreditAmount(window.remaining),
                ' / ',
                window.amount_unit === 'USD' ? '$' : '',
                fmtCreditAmount(window.limit),
                window.amount_unit && window.amount_unit !== 'USD' ? ' ' + window.amount_unit : '',
              ],
            })
            : window.reset_in_seconds != null && jsxs('span', {
              className: 'tabular-nums',
              children: ['reset ', fmtReset(window.reset_in_seconds)],
            }),
        ],
      }),
      jsx(ProgressBar, { pctRemaining: remainingPct(window) }),
      window.remaining != null && window.limit != null && window.reset_in_seconds != null && jsx('div', {
        className: 'text-right text-[0.5625rem] tabular-nums',
        style: { color: 'var(--ui-text-quaternary, #666)' },
        children: 'reset ' + fmtReset(window.reset_in_seconds),
      }),
    ],
  }, provider + '-' + index)
}

function ProviderCard({ provider, data }) {
  var status = statusOf(data)
  var ok = status === 'ok'
  var dotVariant = !ok ? 'error' : (data.limit_reached ? 'error' : 'success')
  var meta = PROVIDERS[provider] || {}
  var label = meta.label || provider
  var icon = meta.icon || 'gauge'
  var windows = (ok && data.windows) || []

  return jsxs('div', {
    className: 'rounded-lg border p-2.5 flex flex-col gap-2',
    style: { borderColor: 'var(--ui-stroke-secondary, #333)' },
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between',
        children: [
          jsxs('div', {
            className: 'flex items-center gap-1.5',
            children: [
              jsx(Codicon, {
                name: icon,
                className: 'text-[0.875rem]',
                style: { color: 'var(--ui-text-secondary, #aaa)' },
              }),
              jsx('span', { className: 'text-xs font-medium', children: label }),
            ],
          }),
          jsxs('div', {
            className: 'flex items-center gap-1',
            children: [
              jsx(StatusDot, { variant: dotVariant }),
              data && data.plan && jsx(Badge, {
                variant: 'outline',
                className: 'text-[0.5625rem] px-1',
                children: String(data.plan).toUpperCase(),
              }),
              !ok && jsx(Badge, {
                variant: 'outline',
                className: 'text-[0.5625rem] px-1',
                children: STATUS_LABEL[status] || status,
              }),
            ],
          }),
        ],
      }),
      ok && windows.map(function(window, i) {
        return jsx(WindowRow, { provider: provider, window: window, index: i }, provider + '-' + i)
      }),
      !ok && jsx('div', {
        className: 'text-[0.625rem]',
        style: { color: 'var(--ui-text-tertiary, #888)' },
        children: data && data.message ? data.message : (STATUS_LABEL[status] || status),
      }),
    ],
  })
}

function QuotaChip() {
  var query = useQuota()
  var data = query.data
  var providers = (data && data.providers) || {}
  var names = Object.keys(providers)
  if (query.isError || (!query.isLoading && names.length === 0)) return null

  var lowest = null
  var lowestPct = 100
  var hasProblem = false
  names.forEach(function(name) {
    var p = providers[name]
    if (!p) return
    if (!isOk(p)) {
      if (statusOf(p) !== 'no_key' && statusOf(p) !== 'no_token') hasProblem = true
      return
    }
    (p.windows || []).forEach(function(w) {
      var rem = remainingPct(w)
      if (rem < lowestPct) { lowestPct = rem; lowest = name }
    })
  })

  var color = hasProblem && lowest == null
    ? 'var(--ui-warning, #f59e0b)'
    : pctColor(lowestPct)
  var chipLabel = lowest ? ((PROVIDERS[lowest] || {}).chip || '?') : (hasProblem ? '!' : '...')

  return jsx(Tip, {
    label: lowest
      ? chipLabel + ' ' + Math.round(lowestPct) + '% remaining — click for details'
      : (hasProblem ? 'Quota error — click for details' : 'Loading quota...'),
    children: jsxs('button', {
      type: 'button',
      className: 'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] cursor-pointer',
      onClick: function() { haptic('tap'); host.navigate('/llm-quota') },
      children: [
        jsx(Codicon, {
          name: 'gauge',
          className: 'text-[0.75rem]',
          style: { color: color },
        }),
        lowest && jsxs('span', {
          className: 'tabular-nums font-medium',
          style: { color: color },
          children: [Math.round(lowestPct), '%'],
        }),
      ],
    }),
  })
}

function QuotaPane() {
  var query = useQuota()
  var data = query.data
  var isLoading = query.isLoading
  var isError = query.isError
  var error = query.error
  var refetch = query.refetch
  var providers = (data && data.providers) || {}
  var listed = PROVIDER_ORDER.filter(function(name) { return !!providers[name] })

  return jsxs('div', {
    className: 'flex h-full flex-col gap-2',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between px-3 pt-3 pb-1 shrink-0',
        children: [
          jsxs('div', {
            className: 'flex items-center gap-1.5',
            children: [
              jsx(Codicon, {
                name: 'gauge',
                className: 'text-sm',
                style: { color: 'var(--ui-text-secondary, #aaa)' },
              }),
              jsx('span', {
                className: 'text-sm font-medium',
                children: 'LLM Quota Monitor',
              }),
            ],
          }),
          jsx(Button, {
            variant: 'ghost',
            size: 'icon',
            className: 'h-6 w-6',
            onClick: function() { refetch() },
            children: jsx(Codicon, { name: 'refresh', className: 'text-xs' }),
          }),
        ],
      }),
      isLoading && jsx('div', {
        className: 'flex flex-1 items-center justify-center',
        children: jsx(GlyphSpinner, { size: 20 }),
      }),
      isError && jsx('div', {
        className: 'p-3',
        children: jsx(ErrorState, {
          title: 'Failed to load quota data',
          message: (error && error.message) || String(error),
        }),
      }),
      !isLoading && !isError && jsx(ScrollArea, {
        className: 'flex-1 px-3 pb-3',
        children: jsxs('div', {
          className: 'flex min-h-full flex-col gap-2',
          children: [
            listed.length > 0
              ? listed.map(function(provider) {
                  return jsx(ProviderCard, { provider: provider, data: providers[provider] }, provider)
                })
              : jsx('div', {
                  className: 'flex flex-1 items-center justify-center p-3 text-center text-xs',
                  style: { color: 'var(--ui-text-tertiary, #888)' },
                  children: 'No providers returned by the backend',
                }),
            data && data.timestamp && jsx('div', {
              className: 'pt-1 text-center text-[0.5625rem]',
              style: { color: 'var(--ui-text-quaternary, #666)' },
              children: 'Updated ' + fmtTime(data.timestamp),
            }),
          ],
        }),
      }),
    ],
  })
}

export default {
  id: ID,
  name: 'LLM Quota Monitor',
  register: function(ctx) {
    _ctx = ctx

    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'quota',
      data: { placement: 'right', width: '260px' },
      render: function() { return jsx(QuotaPane, {}) },
    })

    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 120,
      render: function() { return jsx(QuotaChip, {}) },
    })
  },
}
