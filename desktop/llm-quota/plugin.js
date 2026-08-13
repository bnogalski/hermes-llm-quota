/**
 * LLM Quota Monitor - Hermes Desktop pane.
 *
 * Install at $HERMES_HOME/desktop-plugins/llm-quota/plugin.js.
 * Folder name and exported id must match the dashboard/backend namespace
 * so ctx.rest('/all') reaches /api/plugins/llm-quota/all.
 */

import {
  haptic, host, useQuery, ROUTES_AREA, SIDEBAR_NAV_AREA,
  ScrollArea, GlyphSpinner, ErrorState,
  StatusDot, Badge, Button, Tip, Codicon,
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'llm-quota'
const REFETCH_MS = 60_000
const PROVIDERS = {
  nous: { label: 'Nous Portal', icon: 'layers', chip: 'NOU' },
  zai: { label: 'Z.AI', icon: 'layers', chip: 'ZAI' },
  codex: { label: 'Codex', icon: 'layers', chip: 'CDX' },
  grok: { label: 'Grok', icon: 'layers', chip: 'GRK' },
  openrouter: { label: 'OpenRouter', icon: 'layers', chip: 'OR' },
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

let _apiGet = null

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
    queryFn: () => _apiGet('/all'),
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
  return new Date(unixTs * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function fmtCreditAmount(value) {
  if (value == null || value === '') return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function pctColor(pctRemaining) {
  if (pctRemaining <= 15) return 'var(--ui-danger, #f87171)'
  if (pctRemaining <= 40) return 'var(--ui-warning, #f59e0b)'
  return 'var(--ui-accent)'
}

function ProgressBar({ pctRemaining }) {
  const used = Math.max(0, Math.min(100, 100 - pctRemaining))
  const color = pctColor(pctRemaining)
  return jsxs('div', {
    className: 'flex items-center gap-2',
    children: [
      jsx('div', {
        className: 'relative h-1.5 flex-1 overflow-hidden rounded-full',
        style: { backgroundColor: 'var(--ui-stroke-secondary)' },
        children: jsx('div', {
          className: 'absolute inset-y-0 left-0 rounded-full transition-all duration-500',
          style: { width: used + '%', backgroundColor: color },
        }),
      }),
      jsx('span', {
        className: 'w-7 text-right text-[0.625rem] font-medium tabular-nums',
        style: { color },
        children: Math.round(pctRemaining) + '%',
      }),
    ],
  })
}

function WindowRow({ provider, window, index }) {
  const hasCredits = window.remaining != null && window.limit != null
  return jsxs('div', {
    className: 'flex flex-col gap-0.5',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between text-[0.625rem] text-(--ui-text-tertiary)',
        children: [
          jsx('span', { children: window.label || window.type }),
          hasCredits
            ? jsxs('span', {
                className: 'tabular-nums',
                children: [
                  window.amount_unit === 'USD' ? '$' : '', fmtCreditAmount(window.remaining),
                  ' / ', window.amount_unit === 'USD' ? '$' : '', fmtCreditAmount(window.limit),
                  window.amount_unit && window.amount_unit !== 'USD' ? ' ' + window.amount_unit : '',
                ],
              })
            : window.reset_in_seconds != null && jsx('span', {
                className: 'tabular-nums',
                children: 'reset ' + fmtReset(window.reset_in_seconds),
              }),
        ],
      }),
      jsx(ProgressBar, { pctRemaining: remainingPct(window) }),
      hasCredits && window.reset_in_seconds != null && jsx('div', {
        className: 'text-right text-[0.5625rem] tabular-nums text-(--ui-text-quaternary)',
        children: 'reset ' + fmtReset(window.reset_in_seconds),
      }),
    ],
  }, provider + '-' + index)
}

function ProviderCard({ provider, data }) {
  const status = statusOf(data)
  const ok = status === 'ok'
  const tone = !ok ? 'bad' : (data.limit_reached ? 'bad' : 'good')
  const meta = PROVIDERS[provider] || {}
  const windows = ok && Array.isArray(data.windows) ? data.windows : []

  return jsxs('div', {
    className: 'flex flex-col gap-2 rounded-lg border p-2.5',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between',
        children: [
          jsxs('div', {
            className: 'flex items-center gap-1.5',
            children: [
              jsx(Codicon, { name: meta.icon || 'layers', className: 'text-[0.875rem] text-(--ui-text-secondary)' }),
              jsx('span', { className: 'text-xs font-medium', children: meta.label || provider }),
            ],
          }),
          jsxs('div', {
            className: 'flex items-center gap-1',
            children: [
              jsx(StatusDot, { tone }),
              data && data.plan && jsx(Badge, {
                variant: 'outline', size: 'xs', children: String(data.plan).toUpperCase(),
              }),
              !ok && jsx(Badge, {
                variant: 'outline', size: 'xs', children: STATUS_LABEL[status] || status,
              }),
            ],
          }),
        ],
      }),
      ok && windows.map((window, i) => jsx(WindowRow, {
        provider, window, index: i,
      }, provider + '-' + i)),
      !ok && jsx('div', {
        className: 'text-[0.625rem] text-(--ui-text-tertiary)',
        children: data && data.message ? data.message : (STATUS_LABEL[status] || status),
      }),
    ],
  })
}

function QuotaChip() {
  const query = useQuota()
  const providers = (query.data && query.data.providers) || {}
  const names = Object.keys(providers)
  if (!query.isLoading && names.length === 0 && !query.isError) return null

  // When the query itself errors, ignore stale cached data — show the error.
  let lowest = null
  let lowestPct = 100
  let hasProblem = query.isError

  if (!query.isError) {
    names.forEach(name => {
      const provider = providers[name]
      if (!provider) return
      if (!isOk(provider)) {
        if (!['no_key', 'no_token'].includes(statusOf(provider))) hasProblem = true
        return
      }
      ;(provider.windows || []).forEach(window => {
        const remaining = remainingPct(window)
        if (remaining < lowestPct) { lowestPct = remaining; lowest = name }
      })
    })
  }

  const color = hasProblem ? 'var(--ui-warning, #f59e0b)' : pctColor(lowestPct)
  const chipLabel = lowest ? (PROVIDERS[lowest] || {}).chip : (hasProblem ? '!' : '...')
  return jsx(Tip, {
    label: lowest
      ? chipLabel + ' ' + Math.round(lowestPct) + '% remaining - click for details'
      : (hasProblem ? 'Quota error - click for details' : 'Loading quota...'),
    children: jsxs('button', {
      type: 'button',
      className: 'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem]',
      onClick: () => { haptic('tap'); host.navigate('/llm-quota') },
      children: [
        jsx(Codicon, { name: 'layers', className: 'text-[0.75rem]', style: { color } }),
        lowest && jsx('span', { className: 'font-medium tabular-nums', style: { color }, children: Math.round(lowestPct) + '%' }),
      ],
    }),
  })
}

function QuotaPane() {
  const query = useQuota()
  const data = query.data
  const providers = (data && data.providers) || {}
  const listed = PROVIDER_ORDER.filter(name => !!providers[name])

  return jsxs('div', {
    className: 'flex h-full flex-col gap-2',
    children: [
      jsxs('div', {
        className: 'flex shrink-0 items-center justify-between px-3 pb-1 pt-3',
        children: [
          jsxs('div', {
            className: 'flex items-center gap-1.5',
            children: [
              jsx(Codicon, { name: 'layers', className: 'text-sm text-(--ui-text-secondary)' }),
              jsx('span', { className: 'text-sm font-medium', children: 'LLM Quota Monitor' }),
            ],
          }),
          jsx(Button, {
            variant: 'ghost', size: 'icon-xs',
            onClick: () => query.refetch(),
            children: jsx(Codicon, { name: 'refresh', className: 'text-xs' }),
          }),
        ],
      }),
      query.isLoading && jsx('div', {
        className: 'flex flex-1 items-center justify-center',
        children: jsx(GlyphSpinner, { size: 20 }),
      }),
      query.isError && jsx('div', {
        className: 'p-3',
        children: jsx(ErrorState, {
          title: 'Failed to load quota data',
          description: query.error && query.error.message ? query.error.message : String(query.error),
        }),
      }),
      !query.isLoading && !query.isError && jsx(ScrollArea, {
        className: 'flex-1 px-3 pb-3',
        children: jsxs('div', {
          className: 'flex min-h-full flex-col gap-2',
          children: [
            listed.length > 0
              ? listed.map(provider => jsx(ProviderCard, { provider, data: providers[provider] }, provider))
              : jsx('div', {
                  className: 'flex flex-1 items-center justify-center p-3 text-center text-xs text-(--ui-text-tertiary)',
                  children: 'No providers returned by the backend',
                }),
            data && data.timestamp && jsx('div', {
              className: 'pt-1 text-center text-[0.5625rem] text-(--ui-text-quaternary)',
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
  description: 'Live quota for Z.AI, Codex, Grok, Nous Portal, and OpenRouter.',
  register(ctx) {
    _apiGet = function(path) {
      return ctx.rest(path)
    }

    ctx.register({
      id: 'pane', area: 'panes', title: 'quota',
      data: { placement: 'right', width: '260px' },
      render: () => jsx(QuotaPane, {}),
    })
    ctx.register({
      id: 'chip', area: 'statusBar.right', order: 120,
      render: () => jsx(QuotaChip, {}),
    })
    ctx.register({
      id: 'page', area: ROUTES_AREA,
      data: { path: '/llm-quota' },
      render: () => jsx(QuotaPane, {}),
    })
    ctx.register({
      id: 'nav', area: SIDEBAR_NAV_AREA,
      data: { path: '/llm-quota', label: 'Quota', codicon: 'layers' },
    })
  },
}
