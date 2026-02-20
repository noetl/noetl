import { useEffect, useMemo, useRef, useState } from 'react';
import { createAuth0Client } from '@auth0/auth0-spa-js';

const STORAGE_TOKEN_KEY = 'noetl_gateway_example_session_token';
const STORAGE_USER_KEY = 'noetl_gateway_example_user';

const DEFAULT_GATEWAY_URL = (import.meta.env.VITE_GATEWAY_URL || 'https://gateway.mestumre.dev').trim();
const DEFAULT_AUTH0_DOMAIN = (import.meta.env.VITE_AUTH0_DOMAIN || 'mestumre-development.us.auth0.com').trim();
const DEFAULT_AUTH0_CLIENT_ID = (
  import.meta.env.VITE_AUTH0_CLIENT_ID || 'Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN'
).trim();
const DEFAULT_PLAYBOOK_PATH = (
  import.meta.env.VITE_AMADEUS_PLAYBOOK_PATH || 'api_integration/amadeus_ai_api'
).trim();
const MAX_SSE_RECONNECT_ATTEMPTS = 5;
const SSE_RECONNECT_DELAY_MS = 2000;
const CALLBACK_TIMEOUT_MS = 120000;
const CALLBACK_CACHE_TTL_MS = 5 * 60 * 1000;
const CALLBACK_FALLBACK_POLL_WINDOW_MS = 45000;

function normalizeBaseUrl(url) {
  return (url || '').trim().replace(/\/+$/, '');
}

function safeParseJson(raw, fallback) {
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseJsonText(value) {
  if (typeof value !== 'string') {
    return value;
  }

  const text = value.trim();
  if (!text) {
    return value;
  }

  if (!(text.startsWith('{') || text.startsWith('[') || text.startsWith('"'))) {
    return value;
  }

  try {
    return JSON.parse(text);
  } catch {
    return value;
  }
}

function unwrapResultPayload(value) {
  let current = parseJsonText(value);
  const maxDepth = 8;

  for (let depth = 0; depth < maxDepth; depth += 1) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) {
      return current;
    }

    if (
      current.kind &&
      Object.prototype.hasOwnProperty.call(current, 'data') &&
      (typeof current.data === 'object' || typeof current.data === 'string')
    ) {
      current = parseJsonText(current.data);
      continue;
    }

    if (
      Object.prototype.hasOwnProperty.call(current, 'result') &&
      (typeof current.result === 'object' || typeof current.result === 'string')
    ) {
      current = parseJsonText(current.result);
      continue;
    }

    if (
      Object.prototype.hasOwnProperty.call(current, 'data') &&
      (typeof current.data === 'object' || typeof current.data === 'string')
    ) {
      current = parseJsonText(current.data);
      continue;
    }

    return current;
  }

  return current;
}

function extractTextOutput(value) {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  if (Array.isArray(value)) {
    return null;
  }

  if (typeof value !== 'object') {
    return null;
  }

  const preferredKeys = [
    'summary_text',
    'summary',
    'textOutput',
    'text_output',
    'message',
    'answer',
    'response',
    'result',
  ];

  for (const key of preferredKeys) {
    const nested = extractTextOutput(value[key]);
    if (nested) {
      return nested;
    }
  }

  return null;
}

function scorePayloadCandidate(payload, event) {
  let score = 0;
  const textOutput = extractTextOutput(payload);

  if (textOutput) {
    score += 80;
  }

  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    const keys = Object.keys(payload);
    if (
      keys.includes('summary') ||
      keys.includes('summary_text') ||
      keys.includes('textOutput') ||
      keys.includes('text_output') ||
      keys.includes('offers_preview')
    ) {
      score += 40;
    }

    if (keys.length <= 3 && keys.includes('command_id')) {
      score -= 20;
    }
  }

  const eventType = String(event?.event_type || '').toLowerCase();
  const nodeName = String(event?.node_name || '').toLowerCase();

  if (eventType === 'call.done') {
    score += 20;
  }
  if (eventType === 'step.exit') {
    score += 10;
  }
  if (nodeName.includes('extract_summary')) {
    score += 60;
  }
  if (nodeName.includes('send_callback')) {
    score += 50;
  }

  return score;
}

function extractExecutionOutput(events, executionData = null) {
  const candidates = [];

  function pushCandidate(rawValue, event, source) {
    if (rawValue === null || rawValue === undefined) {
      return;
    }

    const payload = unwrapResultPayload(rawValue);
    if (payload === null || payload === undefined) {
      return;
    }

    candidates.push({
      source,
      event: event || null,
      payload,
      textOutput: extractTextOutput(payload),
      score: scorePayloadCandidate(payload, event),
    });
  }

  if (executionData && typeof executionData === 'object') {
    pushCandidate(executionData.result, null, 'execution.result');
    pushCandidate(executionData.output_result, null, 'execution.output_result');
    pushCandidate(executionData.output, null, 'execution.output');
  }

  for (const event of events || []) {
    pushCandidate(event?.result, event, 'event.result');
    pushCandidate(event?.output_result, event, 'event.output_result');

    const parsedContext = parseJsonText(event?.context);
    if (parsedContext && typeof parsedContext === 'object' && !Array.isArray(parsedContext)) {
      pushCandidate(parsedContext.result, event, 'event.context.result');
      pushCandidate(parsedContext.data, event, 'event.context.data');
    }
  }

  if (candidates.length === 0) {
    return null;
  }

  candidates.sort((a, b) => b.score - a.score);
  return candidates[0];
}

function resolveAuth0RedirectUri() {
  const configuredRedirect = (import.meta.env.VITE_AUTH0_REDIRECT_URI || '').trim();
  if (configuredRedirect) {
    return configuredRedirect;
  }

  const isLocalhost =
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  if (isLocalhost) {
    return `${window.location.origin}/login.html`;
  }

  return `${window.location.origin}${window.location.pathname}`;
}

function isLocalhost() {
  return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
}

export default function App() {
  const storedToken = localStorage.getItem(STORAGE_TOKEN_KEY) || '';
  const storedUser = safeParseJson(localStorage.getItem(STORAGE_USER_KEY), null);

  const [gatewayUrl, setGatewayUrl] = useState(DEFAULT_GATEWAY_URL);
  const [auth0Domain, setAuth0Domain] = useState(DEFAULT_AUTH0_DOMAIN);
  const [auth0ClientId, setAuth0ClientId] = useState(DEFAULT_AUTH0_CLIENT_ID);
  const [auth0Token, setAuth0Token] = useState('');

  const [sessionTokenInput, setSessionTokenInput] = useState(storedToken);
  const [sessionToken, setSessionToken] = useState(storedToken);
  const [user, setUser] = useState(storedUser);

  const [playbookPath, setPlaybookPath] = useState(DEFAULT_PLAYBOOK_PATH);
  const [query, setQuery] = useState('I want a one-way flight from SFO to JFK on July 15, 2026 for 1 adult');

  const [busy, setBusy] = useState(false);
  const [statusText, setStatusText] = useState('Ready. Default gateway is set to https://gateway.mestumre.dev.');
  const [statusType, setStatusType] = useState('info');

  const [executionId, setExecutionId] = useState('');
  const [executionStatus, setExecutionStatus] = useState('');
  const [executionSummary, setExecutionSummary] = useState(null);
  const [callbackResult, setCallbackResult] = useState(null);
  const [sseConnected, setSseConnected] = useState(false);
  const [sseClientId, setSseClientId] = useState('');
  const [diagnosticsRunning, setDiagnosticsRunning] = useState(false);
  const [diagnosticsGeneratedAt, setDiagnosticsGeneratedAt] = useState('');
  const [diagnosticsReport, setDiagnosticsReport] = useState('');
  const callbackHandledRef = useRef(false);
  const auth0ClientRef = useRef(null);
  const eventSourceRef = useRef(null);
  const pendingCallbacksRef = useRef(new Map());
  const recentCallbacksRef = useRef(new Map());
  const sseReconnectAttemptsRef = useRef(0);
  const sseReconnectTimerRef = useRef(null);
  const sseClientIdRef = useRef('');

  const apiBase = useMemo(() => normalizeBaseUrl(gatewayUrl), [gatewayUrl]);
  const useDevProxy = useMemo(
    () => isLocalhost() && (import.meta.env.VITE_USE_DEV_PROXY || 'true').toLowerCase() !== 'false',
    []
  );

  function setStatus(text, type = 'info') {
    setStatusText(text);
    setStatusType(type);
  }

  function persistSession(token, nextUser) {
    localStorage.setItem(STORAGE_TOKEN_KEY, token);
    localStorage.setItem(STORAGE_USER_KEY, JSON.stringify(nextUser || null));
    setSessionToken(token);
    setSessionTokenInput(token);
    setUser(nextUser || null);
  }

  function clearSession() {
    rejectPendingCallbacks('Session was cleared.');
    disconnectSse();

    localStorage.removeItem(STORAGE_TOKEN_KEY);
    localStorage.removeItem(STORAGE_USER_KEY);
    setSessionToken('');
    setSessionTokenInput('');
    setUser(null);
    setExecutionId('');
    setExecutionStatus('');
    setExecutionSummary(null);
    setCallbackResult(null);
    setStatus('Session cleared.', 'info');
  }

  async function exchangeAuth0TokenWithGateway(idToken) {
    const data = await request('/api/auth/login', {
      method: 'POST',
      body: {
        auth0_token: idToken,
        auth0_domain: auth0Domain.trim(),
      },
    });

    if (!data.session_token) {
      throw new Error('Login succeeded but no session_token was returned.');
    }

    persistSession(data.session_token, data.user || null);
    setStatus(`Authenticated as ${data.user?.email || 'user'}.`, 'success');
    setAuth0Token('');
  }

  async function request(path, { method = 'GET', body, token } = {}) {
    const headers = {
      'Content-Type': 'application/json',
    };

    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const requestUrl = useDevProxy ? path : `${apiBase}${path}`;
    const response = await fetch(requestUrl, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    const text = await response.text();
    const data = text ? safeParseJson(text, { raw: text }) : {};

    if (!response.ok) {
      if (response.status === 502 && useDevProxy) {
        if (path.startsWith('/api/auth/')) {
          throw new Error(
            'Gateway auth endpoint returned 502 upstream. Verify directly: curl -i -X POST https://gateway.mestumre.dev/api/auth/login -H "Content-Type: application/json" --data "{}"'
          );
        }
        throw new Error(
          'Local dev proxy returned 502 (or upstream is unavailable). Check Vite terminal logs for proxy target/reachability, then restart npm run dev.'
        );
      }

      const errorMessage =
        (data && data.error) ||
        (data && data.detail) ||
        `${method} ${path} failed with ${response.status}`;
      throw new Error(errorMessage);
    }

    return data;
  }

  function getSseUrl(token) {
    const clientParam = sseClientIdRef.current
      ? `&client_id=${encodeURIComponent(sseClientIdRef.current)}`
      : '';
    const ssePath = `/events?session_token=${encodeURIComponent(token)}${clientParam}`;
    return useDevProxy ? ssePath : `${apiBase}${ssePath}`;
  }

  function clearSseReconnectTimer() {
    if (sseReconnectTimerRef.current) {
      window.clearTimeout(sseReconnectTimerRef.current);
      sseReconnectTimerRef.current = null;
    }
  }

  function rejectPendingCallbacks(message) {
    for (const [, pending] of pendingCallbacksRef.current.entries()) {
      window.clearTimeout(pending.timeoutId);
      pending.reject(new Error(message));
    }
    pendingCallbacksRef.current.clear();
  }

  function pruneRecentCallbacks() {
    const now = Date.now();
    for (const [requestId, cached] of recentCallbacksRef.current.entries()) {
      if (now - cached.receivedAt > CALLBACK_CACHE_TTL_MS) {
        recentCallbacksRef.current.delete(requestId);
      }
    }
  }

  function cacheRecentCallback(requestId, payload) {
    pruneRecentCallbacks();
    recentCallbacksRef.current.set(requestId, {
      payload,
      receivedAt: Date.now(),
    });
  }

  function disconnectSse(options = {}) {
    const { preserveClientId = false } = options;
    clearSseReconnectTimer();
    sseReconnectAttemptsRef.current = 0;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setSseConnected(false);
    if (!preserveClientId) {
      setSseClientId('');
      sseClientIdRef.current = '';
      recentCallbacksRef.current.clear();
    }
  }

  function registerPendingCallback(requestId, timeoutMs = CALLBACK_TIMEOUT_MS) {
    return new Promise((resolve, reject) => {
      pruneRecentCallbacks();

      const cached = recentCallbacksRef.current.get(requestId);
      if (cached) {
        recentCallbacksRef.current.delete(requestId);
        const payload = cached.payload;
        if (String(payload.status || '').toUpperCase() === 'FAILED' || payload.errorMessage) {
          reject(new Error(payload.errorMessage || 'Playbook execution failed.'));
          return;
        }
        resolve(payload);
        return;
      }

      const existing = pendingCallbacksRef.current.get(requestId);
      if (existing) {
        window.clearTimeout(existing.timeoutId);
        pendingCallbacksRef.current.delete(requestId);
      }

      const timeoutId = window.setTimeout(() => {
        const pending = pendingCallbacksRef.current.get(requestId);
        if (!pending) {
          return;
        }
        pendingCallbacksRef.current.delete(requestId);
        pending.reject(new Error('Playbook callback timed out.'));
      }, timeoutMs);

      pendingCallbacksRef.current.set(requestId, {
        timeoutId,
        resolve: (value) => {
          window.clearTimeout(timeoutId);
          resolve(value);
        },
        reject: (error) => {
          window.clearTimeout(timeoutId);
          reject(error);
        },
      });
    });
  }

  function cancelPendingCallback(requestId, reason = 'Playbook callback cancelled.') {
    const pending = pendingCallbacksRef.current.get(requestId);
    if (!pending) {
      return;
    }

    pendingCallbacksRef.current.delete(requestId);
    pending.reject(new Error(reason));
  }

  function connectSse(token, options = {}) {
    const { reconnect = false } = options;
    if (!token) {
      return;
    }

    clearSseReconnectTimer();

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const sseUrl = getSseUrl(token);
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    if (!reconnect) {
      setSseConnected(false);
    }

    es.onopen = () => {
      sseReconnectAttemptsRef.current = 0;
    };

    es.addEventListener('message', (event) => {
      const msg = safeParseJson(event.data, null);
      const nextClientId = msg?.result?.clientId;
      if (!nextClientId) {
        return;
      }

      sseClientIdRef.current = nextClientId;
      setSseClientId(nextClientId);
      setSseConnected(true);
    });

    es.addEventListener('playbook/result', (event) => {
      const msg = safeParseJson(event.data, null);
      const params = msg?.params || {};
      const requestId = params.requestId || params.request_id;
      if (!requestId) {
        return;
      }

      const isFailure = String(params.status || '').toUpperCase() === 'FAILED' || Boolean(params.error);
      const errorMessage = params.error?.message || null;

      const textOutput =
        params.data?.textOutput ||
        params.data?.text_output ||
        params.data?.summary ||
        params.data?.result ||
        null;

      const payload = {
        requestId,
        executionId: params.executionId || params.execution_id,
        status: params.status || 'COMPLETED',
        textOutput,
        data: params.data || null,
        errorMessage,
      };

      const pending = pendingCallbacksRef.current.get(requestId);
      if (!pending) {
        cacheRecentCallback(requestId, payload);
        return;
      }

      pendingCallbacksRef.current.delete(requestId);

      if (isFailure) {
        pending.reject(new Error(errorMessage || 'Playbook execution failed.'));
        return;
      }

      pending.resolve(payload);
    });

    es.onerror = () => {
      if (eventSourceRef.current !== es) {
        return;
      }

      setSseConnected(false);

      if (sseReconnectAttemptsRef.current >= MAX_SSE_RECONNECT_ATTEMPTS) {
        rejectPendingCallbacks('SSE connection lost.');
        return;
      }

      sseReconnectAttemptsRef.current += 1;
      const reconnectDelay = SSE_RECONNECT_DELAY_MS;
      sseReconnectTimerRef.current = window.setTimeout(() => {
        connectSse(token, { reconnect: true });
      }, reconnectDelay);
    };
  }

  async function waitForSseClientId(timeoutMs = 10000) {
    if (sseClientIdRef.current) {
      return true;
    }

    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      await sleep(100);
      if (sseClientIdRef.current) {
        return true;
      }
    }

    return false;
  }

  async function runProbe({ id, label, method = 'GET', path, body }) {
    const startedAt = Date.now();
    const timeoutMs = 12000;
    const requestUrl = useDevProxy ? path : `${apiBase}${path}`;
    const headers = body === undefined ? {} : { 'Content-Type': 'application/json' };

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(requestUrl, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });

      const text = await response.text();
      const compactBody = text.replace(/\s+/g, ' ').trim().slice(0, 200);

      return {
        id,
        label,
        method,
        path,
        status: response.status,
        duration_ms: Date.now() - startedAt,
        body_preview: compactBody,
      };
    } catch (error) {
      const message =
        error?.name === 'AbortError'
          ? `timeout after ${timeoutMs}ms`
          : error?.message || 'request failed';

      return {
        id,
        label,
        method,
        path,
        status: 0,
        duration_ms: Date.now() - startedAt,
        body_preview: '',
        error: message,
      };
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function isProbeHealthy(probe) {
    if (!probe) {
      return false;
    }

    switch (probe.id) {
      case 'health':
        return probe.status === 200 && !probe.body_preview.toLowerCase().includes('<!doctype html');
      case 'graphql_auth':
        return probe.status === 401 || probe.status === 403;
      case 'auth_login_schema':
        return probe.status === 400 || probe.status === 401 || probe.status === 422;
      case 'auth_login_fake_token':
        return probe.status === 200 || probe.status === 400 || probe.status === 401 || probe.status === 403 || probe.status === 422;
      case 'auth_validate_dummy':
        return probe.status === 200 || probe.status === 401 || probe.status === 422;
      case 'auth_check_access_dummy':
        return probe.status === 200 || probe.status === 401 || probe.status === 403 || probe.status === 422;
      default:
        return probe.status >= 200 && probe.status < 300;
    }
  }

  function buildDiagnosticsReport(probes) {
    const generatedAt = new Date().toISOString();
    const byId = Object.fromEntries(probes.map((probe) => [probe.id, probe]));
    const health = byId.health;
    const graphqlAuth = byId.graphql_auth;
    const authProbes = [
      byId.auth_login_schema,
      byId.auth_login_fake_token,
      byId.auth_validate_dummy,
      byId.auth_check_access_dummy,
    ].filter(Boolean);
    const authHas502 = authProbes.some((probe) => probe.status === 502);
    const networkErrors = probes.filter((probe) => probe.status === 0);
    const healthLooksLikeLocalHtml =
      health?.status === 200 && (health?.body_preview || '').toLowerCase().includes('<!doctype html');

    const triage = [];
    if (healthLooksLikeLocalHtml) {
      triage.push('Health probe returned local HTML, not gateway health output. Check Vite /health proxy and restart dev server.');
    }
    if (health?.status === 200 && authHas502) {
      triage.push(
        'Gateway responds on /health, but auth endpoints return 502. Likely failure is in gateway auth dependency chain (NoETL auth playbooks, callback path, NATS, DB, DNS).'
      );
    }
    if (health?.status !== 200) {
      triage.push('Gateway /health is not healthy. Diagnose ingress/service/pod reachability first.');
    }
    if (networkErrors.length > 0) {
      triage.push('One or more probes failed at network level from browser context.');
    }
    if (graphqlAuth && (graphqlAuth.status === 401 || graphqlAuth.status === 403)) {
      triage.push('GraphQL auth guard is active (expected before login).');
    }
    if (useDevProxy) {
      triage.push(`Requests are routed through Vite proxy (${window.location.origin}), so browser CORS is bypassed.`);
    }
    if (triage.length === 0) {
      triage.push('No critical issues detected by quick probes.');
    }

    const nextSteps = [];
    if (authHas502) {
      nextSteps.push('Check gateway logs for /api/auth/login and /api/auth/validate around this timestamp.');
      nextSteps.push(
        'Verify auth system playbooks and callback flow: api_integration/auth0/auth0_login, api_integration/auth0/auth0_validate_session, api_integration/auth0/check_playbook_access.'
      );
      nextSteps.push(
        'Direct probe: curl -i -X POST https://gateway.mestumre.dev/api/auth/login -H "Content-Type: application/json" --data "{}"'
      );
    }
    if (health?.status !== 200) {
      nextSteps.push('Verify gateway /health from Cloudflare and from inside cluster.');
    }
    if (healthLooksLikeLocalHtml) {
      nextSteps.push('Ensure Vite proxy includes /health and restart npm run dev.');
    }
    if (networkErrors.length > 0) {
      nextSteps.push('Restart local dev server and confirm Vite proxy target in terminal output.');
    }
    if (nextSteps.length === 0) {
      nextSteps.push('Proceed with full Auth0 login and playbook execution tests.');
    }

    const lines = [];
    lines.push('Gateway Diagnostics Report');
    lines.push(`Generated: ${generatedAt}`);
    lines.push(`Gateway Base (configured): ${apiBase}`);
    lines.push(
      `Request Routing: ${useDevProxy ? `Vite proxy via ${window.location.origin}` : 'Direct browser to gateway URL'}`
    );
    lines.push('');
    lines.push('Probe Results:');
    probes.forEach((probe) => {
      const marker = isProbeHealthy(probe) ? 'PASS' : 'FAIL';
      const status = probe.status === 0 ? 'NETWORK_ERROR' : String(probe.status);
      const tail = probe.error
        ? ` error="${probe.error}"`
        : probe.body_preview
          ? ` body="${probe.body_preview}"`
          : '';
      lines.push(
        `- [${marker}] ${probe.label}: ${probe.method} ${probe.path} -> ${status} (${probe.duration_ms}ms)${tail}`
      );
    });
    lines.push('');
    lines.push('Triage:');
    triage.forEach((item) => lines.push(`- ${item}`));
    lines.push('');
    lines.push('Recommended Next Steps:');
    nextSteps.forEach((item) => lines.push(`- ${item}`));

    return {
      generatedAt,
      text: lines.join('\n'),
    };
  }

  async function runGatewayDiagnostics() {
    if (diagnosticsRunning) {
      return;
    }

    setDiagnosticsRunning(true);
    setStatus('Running gateway diagnostics probes ...', 'info');

    try {
      const probes = await Promise.all([
        runProbe({
          id: 'health',
          label: 'Gateway health',
          method: 'GET',
          path: '/health',
        }),
        runProbe({
          id: 'graphql_auth',
          label: 'GraphQL auth guard',
          method: 'POST',
          path: '/graphql',
          body: { query: '{ __typename }' },
        }),
        runProbe({
          id: 'auth_login_schema',
          label: 'Auth login endpoint',
          method: 'POST',
          path: '/api/auth/login',
          body: {},
        }),
        runProbe({
          id: 'auth_login_fake_token',
          label: 'Auth login flow (fake token)',
          method: 'POST',
          path: '/api/auth/login',
          body: {
            auth0_token: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkaWFnbm9zdGljIn0.signature',
            auth0_domain: auth0Domain.trim() || DEFAULT_AUTH0_DOMAIN,
          },
        }),
        runProbe({
          id: 'auth_validate_dummy',
          label: 'Auth validate endpoint',
          method: 'POST',
          path: '/api/auth/validate',
          body: { session_token: 'diagnostic-invalid-session-token' },
        }),
        runProbe({
          id: 'auth_check_access_dummy',
          label: 'Auth check-access endpoint',
          method: 'POST',
          path: '/api/auth/check-access',
          body: {
            session_token: 'diagnostic-invalid-session-token',
            playbook_path: playbookPath.trim() || DEFAULT_PLAYBOOK_PATH,
            permission_type: 'execute',
          },
        }),
      ]);

      const report = buildDiagnosticsReport(probes);
      const failed = probes.filter((probe) => !isProbeHealthy(probe)).length;

      setDiagnosticsGeneratedAt(report.generatedAt);
      setDiagnosticsReport(report.text);
      if (failed === 0) {
        setStatus(`Diagnostics complete: ${probes.length}/${probes.length} probes healthy.`, 'success');
      } else {
        setStatus(
          `Diagnostics complete: ${failed}/${probes.length} probes flagged. See Gateway Diagnostics report.`,
          'error'
        );
      }
    } catch (error) {
      setStatus(`Diagnostics failed: ${error.message}`, 'error');
    } finally {
      setDiagnosticsRunning(false);
    }
  }

  function clearDiagnosticsReport() {
    setDiagnosticsGeneratedAt('');
    setDiagnosticsReport('');
    setStatus('Diagnostics report cleared.', 'info');
  }

  async function copyDiagnosticsReport() {
    if (!diagnosticsReport) {
      return;
    }

    try {
      await navigator.clipboard.writeText(diagnosticsReport);
      setStatus('Diagnostics report copied to clipboard.', 'success');
    } catch (error) {
      setStatus(`Failed to copy diagnostics report: ${error.message}`, 'error');
    }
  }

  async function loginWithAuth0Token() {
    if (!auth0Token.trim()) {
      setStatus('Paste an Auth0 ID token first.', 'error');
      return;
    }

    setBusy(true);
    setStatus('Authenticating via /api/auth/login ...', 'info');

    try {
      await exchangeAuth0TokenWithGateway(auth0Token.trim());
    } catch (error) {
      setStatus(`Login failed: ${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function getAuth0Client() {
    const domain = auth0Domain.trim();
    const clientId = auth0ClientId.trim();

    if (!domain) {
      throw new Error('Auth0 domain is required.');
    }
    if (!clientId) {
      throw new Error('Auth0 client ID is required.');
    }

    const redirectUri = resolveAuth0RedirectUri();

    if (auth0ClientRef.current?.key === `${domain}|${clientId}|${redirectUri}`) {
      return auth0ClientRef.current.client;
    }

    const client = await createAuth0Client({
      domain,
      clientId,
      cacheLocation: 'memory',
      authorizationParams: {
        redirect_uri: redirectUri,
        scope: 'openid profile email',
      },
    });

    auth0ClientRef.current = {
      key: `${domain}|${clientId}|${redirectUri}`,
      client,
    };

    return client;
  }

  async function loginWithAuth0Redirect() {
    if (!auth0Domain.trim()) {
      setStatus('Auth0 domain is required.', 'error');
      return;
    }
    if (!auth0ClientId.trim()) {
      setStatus('Auth0 client ID is required.', 'error');
      return;
    }

    const redirectUri = resolveAuth0RedirectUri();
    setStatus(`Redirecting to Auth0 login (callback: ${redirectUri}) ...`, 'info');

    try {
      const client = await getAuth0Client();
      await client.loginWithRedirect();
    } catch (error) {
      setStatus(`Auth0 redirect failed: ${error.message}`, 'error');
    }
  }

  useEffect(() => {
    function handlePageShow() {
      // Recover from browser back/forward cache after external redirect attempts.
      setBusy(false);
    }

    window.addEventListener('pageshow', handlePageShow);
    return () => window.removeEventListener('pageshow', handlePageShow);
  }, []);

  useEffect(() => {
    if (!sessionToken) {
      disconnectSse();
      return;
    }

    connectSse(sessionToken);
    return () => disconnectSse({ preserveClientId: true });
  }, [sessionToken, apiBase, useDevProxy]);

  useEffect(() => {
    return () => {
      rejectPendingCallbacks('Application closed.');
      disconnectSse();
    };
  }, []);

  useEffect(() => {
    if (callbackHandledRef.current) {
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const hasAuthCode = params.has('code') && params.has('state');
    const authError = params.get('error');

    if (!hasAuthCode && !authError) {
      return;
    }

    callbackHandledRef.current = true;

    const finishPath = `${window.location.pathname}${window.location.hash}`;

    setBusy(true);
    setStatus('Handling Auth0 callback ...', 'info');

    (async () => {
      if (authError) {
        const description = params.get('error_description') || authError;
        throw new Error(description);
      }

      const client = await getAuth0Client();
      await client.handleRedirectCallback();
      const claims = await client.getIdTokenClaims();
      const idToken = claims?.__raw || '';

      if (!idToken) {
        throw new Error('Auth0 callback succeeded but ID token is missing.');
      }

      await exchangeAuth0TokenWithGateway(idToken);
    })()
      .catch((error) => {
        setStatus(`Login failed: ${error.message}`, 'error');
      })
      .finally(() => {
        window.history.replaceState({}, document.title, finishPath);
        setBusy(false);
      });
  }, [auth0Domain, auth0ClientId, apiBase]);

  async function validateSessionToken() {
    if (!sessionTokenInput.trim()) {
      setStatus('Enter an existing session token.', 'error');
      return;
    }

    setBusy(true);
    setStatus('Validating session via /api/auth/validate ...', 'info');

    try {
      const token = sessionTokenInput.trim();
      const data = await request('/api/auth/validate', {
        method: 'POST',
        body: {
          session_token: token,
        },
      });

      if (!data.valid) {
        throw new Error('Session is not valid.');
      }

      persistSession(token, data.user || null);
      setStatus(`Session validated for ${data.user?.email || 'user'}.`, 'success');
    } catch (error) {
      setStatus(`Session validation failed: ${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  function applyExecutionSnapshot(execId, snapshot, mode = 'polling-events') {
    if (!snapshot) {
      return;
    }

    const nextStatus = snapshot.status || 'UNKNOWN';
    setExecutionStatus(nextStatus);

    if (snapshot.extracted) {
      setCallbackResult({
        mode,
        execution_id: execId,
        status: nextStatus,
        source: snapshot.extracted.source,
        source_event_type: snapshot.extracted.event?.event_type || null,
        source_node: snapshot.extracted.event?.node_name || null,
        text_output: snapshot.extracted.textOutput,
        data: snapshot.extracted.payload,
      });
    }

    setExecutionSummary({
      status: nextStatus,
      playbook_path: snapshot.path || playbookPath.trim(),
      event_count: snapshot.eventCount,
      end_time: snapshot.endTime,
      latest_error: snapshot.latestError || null,
    });
  }

  async function getExecutionTerminalSnapshot(execId, token) {
    const terminalStatuses = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);

    const data = await request(`/noetl/executions/${execId}?page=1&page_size=100`, {
      method: 'GET',
      token,
    });

    const nextStatus = (data.status || '').toUpperCase();
    if (!terminalStatuses.has(nextStatus)) {
      return {
        terminal: false,
        status: nextStatus || 'UNKNOWN',
      };
    }

    const pageSize = Number(data.pagination?.page_size) || 100;
    const totalPages = Math.max(1, Number(data.pagination?.total_pages) || 1);
    const maxPagesToLoad = Math.min(totalPages, 3);

    const allEvents = Array.isArray(data.events) ? [...data.events] : [];
    for (let page = 2; page <= maxPagesToLoad; page += 1) {
      try {
        const pageData = await request(`/noetl/executions/${execId}?page=${page}&page_size=${pageSize}`, {
          method: 'GET',
          token,
        });
        if (Array.isArray(pageData.events) && pageData.events.length > 0) {
          allEvents.push(...pageData.events);
        }
      } catch (error) {
        void error;
        break;
      }
    }

    const failedEvent = allEvents.find((event) => event.status === 'FAILED' || Boolean(event.error));
    const extracted = extractExecutionOutput(allEvents, data);
    const eventCount = Number(data.pagination?.total_events) || allEvents.length || null;

    return {
      terminal: true,
      status: nextStatus || 'UNKNOWN',
      path: data.path,
      endTime: data.end_time,
      eventCount,
      latestError: failedEvent?.error || null,
      extracted,
    };
  }

  async function pollExecution(execId, token) {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      try {
        const snapshot = await getExecutionTerminalSnapshot(execId, token);
        setExecutionStatus(snapshot.status || 'UNKNOWN');

        if (snapshot.terminal) {
          applyExecutionSnapshot(execId, snapshot, 'polling-events');
          if (snapshot.status === 'COMPLETED') {
            setStatus(`Execution ${execId} completed.`, 'success');
          } else {
            setStatus(`Execution ${execId} finished with ${snapshot.status}.`, 'error');
          }
          return;
        }
      } catch (error) {
        setStatus(`Polling error: ${error.message}`, 'error');
        return;
      }

      await sleep(2000);
    }

    setStatus(`Execution ${execId} is still running after 180 seconds.`, 'info');
  }

  async function runAmadeusPlaybook() {
    if (!sessionToken) {
      setStatus('Authenticate first (login or validate a session token).', 'error');
      return;
    }

    if (!query.trim()) {
      setStatus('Enter a travel query before running the playbook.', 'error');
      return;
    }

    setBusy(true);
    setExecutionId('');
    setExecutionStatus('');
    setExecutionSummary(null);
    setCallbackResult(null);
    setStatus('Starting playbook via /graphql executePlaybook ...', 'info');

    const mutation = `
      mutation ExecuteAmadeus($name: String!, $variables: JSON, $clientId: String) {
        executePlaybook(name: $name, variables: $variables, clientId: $clientId) {
          id
          executionId
          status
          requestId
          name
        }
      }
    `;

    try {
      if (!eventSourceRef.current) {
        connectSse(sessionToken);
      }

      const hasClientId = await waitForSseClientId();
      const callbackClientId = hasClientId ? sseClientIdRef.current : null;

      const response = await request('/graphql', {
        method: 'POST',
        token: sessionToken,
        body: {
          query: mutation,
          variables: {
            name: playbookPath.trim(),
            variables: {
              query: query.trim(),
            },
            clientId: callbackClientId,
          },
        },
      });

      if (response.errors?.length) {
        throw new Error(response.errors[0].message || 'GraphQL execution error');
      }

      const exec = response.data?.executePlaybook;
      const execId = exec?.executionId || exec?.id;

      if (!execId) {
        throw new Error('No execution id returned from executePlaybook');
      }

      setExecutionId(execId);
      setExecutionStatus((exec.status || 'STARTED').toUpperCase());

      if (callbackClientId && exec?.requestId) {
        setStatus(`Execution ${execId} started. Waiting callback ${exec.requestId} ...`, 'info');

        try {
          const callbackPromise = registerPendingCallback(exec.requestId);
          const callbackTaggedPromise = callbackPromise
            .then((value) => ({ type: 'callback', value }))
            .catch((error) => ({ type: 'callback_error', error }));

          const fallbackPollChecks = Math.max(1, Math.floor(CALLBACK_FALLBACK_POLL_WINDOW_MS / 2000));
          let callback = null;

          for (let check = 0; check < fallbackPollChecks; check += 1) {
            const raceResult = await Promise.race([
              callbackTaggedPromise,
              sleep(2000).then(() => ({ type: 'tick' })),
            ]);

            if (raceResult.type === 'callback') {
              callback = raceResult.value;
              break;
            }

            if (raceResult.type === 'callback_error') {
              throw raceResult.error;
            }

            const snapshot = await getExecutionTerminalSnapshot(execId, sessionToken);
            setExecutionStatus(snapshot.status || 'UNKNOWN');

            if (snapshot.terminal) {
              cancelPendingCallback(
                exec.requestId,
                'Execution reached terminal state before callback delivery.'
              );
              applyExecutionSnapshot(execId, snapshot, 'polling-events');

              if (snapshot.status === 'COMPLETED') {
                setStatus(
                  `Execution ${execId} completed via polling fallback (callback channel unavailable).`,
                  'success'
                );
              } else {
                setStatus(
                  `Execution ${execId} finished with ${snapshot.status} via polling fallback.`,
                  'error'
                );
              }
              return;
            }
          }

          if (!callback) {
            cancelPendingCallback(exec.requestId, 'Fallback to execution polling after callback wait window.');
            throw new Error('Callback not received in fallback window');
          }

          const callbackStatus = String(callback.status || 'COMPLETED').toUpperCase();

          setExecutionStatus(callbackStatus);
          setCallbackResult({
            mode: 'sse-callback',
            request_id: callback.requestId,
            execution_id: callback.executionId || execId,
            status: callbackStatus,
            text_output: callback.textOutput,
            data: callback.data,
          });
          setExecutionSummary({
            status: callbackStatus,
            playbook_path: playbookPath.trim(),
            mode: 'callback',
            request_id: callback.requestId,
            execution_id: callback.executionId || execId,
            event_count: null,
            end_time: new Date().toISOString(),
            latest_error: null,
          });

          if (callbackStatus === 'FAILED') {
            setStatus(`Execution ${execId} failed via callback.`, 'error');
          } else {
            setStatus(`Execution ${execId} completed via callback.`, 'success');
          }
          return;
        } catch (callbackError) {
          setStatus(`Callback wait failed: ${callbackError.message}. Falling back to polling ...`, 'info');
        }
      } else {
        setStatus(`Execution ${execId} started without callback channel. Polling status ...`, 'info');
      }

      await pollExecution(execId, sessionToken);
    } catch (error) {
      setStatus(`Playbook execution failed: ${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header>
        <h1>NoETL Gateway React Example</h1>
        <p>
          Minimal example for login + running <code>{DEFAULT_PLAYBOOK_PATH}</code> through Gateway.
        </p>
      </header>

      <section className="card">
        <h2>Gateway Target</h2>
        <label htmlFor="gateway-url">Gateway URL</label>
        <input
          id="gateway-url"
          value={gatewayUrl}
          onChange={(event) => setGatewayUrl(event.target.value)}
          placeholder="https://gateway.mestumre.dev"
          disabled={busy}
        />
        <small>
          Default points to <code>https://gateway.mestumre.dev</code>.
          {useDevProxy ? ' Localhost dev uses Vite proxy for /api, /graphql, /noetl, /events to avoid CORS.' : ''}
        </small>
      </section>

      <section className="card">
        <h2>Login</h2>

        <div className="grid-2">
          <div>
            <label htmlFor="auth0-domain">Auth0 Domain</label>
            <input
              id="auth0-domain"
              value={auth0Domain}
              onChange={(event) => setAuth0Domain(event.target.value)}
              disabled={busy}
            />
          </div>
          <div>
            <label htmlFor="auth0-client-id">Auth0 Client ID</label>
            <input
              id="auth0-client-id"
              value={auth0ClientId}
              onChange={(event) => setAuth0ClientId(event.target.value)}
              disabled={busy}
            />
          </div>
        </div>

        <div className="actions">
          <button type="button" onClick={loginWithAuth0Redirect} disabled={busy}>
            Login with Auth0 (redirect)
          </button>
        </div>

        <small>
          This is the recommended path for developers. The app handles the Auth0 callback and session creation.
        </small>

        <label htmlFor="auth0-token">Auth0 ID Token (JWT)</label>
        <textarea
          id="auth0-token"
          rows={4}
          value={auth0Token}
          onChange={(event) => setAuth0Token(event.target.value)}
          placeholder="Paste ID token from your Auth0 login flow"
          disabled={busy}
        />

        <div className="actions">
          <button type="button" onClick={loginWithAuth0Token} disabled={busy}>
            Login via /api/auth/login
          </button>
        </div>

        <hr />

        <label htmlFor="session-token">Or use existing session token</label>
        <input
          id="session-token"
          value={sessionTokenInput}
          onChange={(event) => setSessionTokenInput(event.target.value)}
          placeholder="Paste session token"
          disabled={busy}
        />

        <div className="actions">
          <button type="button" onClick={validateSessionToken} disabled={busy}>
            Validate via /api/auth/validate
          </button>
          <button type="button" className="secondary" onClick={clearSession} disabled={busy}>
            Clear Session
          </button>
        </div>

        {sessionToken ? (
          <div className="session-box">
            <strong>Authenticated:</strong> {user?.email || 'unknown user'}
            <div>
              <strong>Session token:</strong> <code>{sessionToken.slice(0, 16)}...</code>
            </div>
            <div>
              <strong>Callback channel:</strong>{' '}
              {sseConnected ? 'connected' : 'connecting or unavailable'}
            </div>
            <div>
              <strong>Callback client:</strong>{' '}
              <code>{sseClientId ? `${sseClientId.slice(0, 12)}...` : 'pending'}</code>
            </div>
          </div>
        ) : null}
      </section>

      <section className="card">
        <h2>Run Amadeus Playbook</h2>

        <label htmlFor="playbook-path">Playbook Path</label>
        <input
          id="playbook-path"
          value={playbookPath}
          onChange={(event) => setPlaybookPath(event.target.value)}
          disabled={busy}
        />

        <label htmlFor="travel-query">Travel Query</label>
        <textarea
          id="travel-query"
          rows={3}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          disabled={busy}
        />

        <div className="actions">
          <button type="button" onClick={runAmadeusPlaybook} disabled={busy || !sessionToken}>
            Run executePlaybook
          </button>
        </div>

        {executionId ? (
          <div className="execution-box">
            <div>
              <strong>Execution ID:</strong> <code>{executionId}</code>
            </div>
            <div>
              <strong>Status:</strong> {executionStatus || 'starting'}
            </div>
            {callbackResult?.text_output ? (
              <div>
                <strong>Playbook Response:</strong>
                <pre>{callbackResult.text_output}</pre>
              </div>
            ) : null}
            {executionSummary ? (
              <pre>{JSON.stringify(executionSummary, null, 2)}</pre>
            ) : null}
            {callbackResult ? (
              <pre>{JSON.stringify(callbackResult, null, 2)}</pre>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="card">
        <h2>Gateway Diagnostics</h2>
        <p className="diagnostics-description">
          Runs health/auth probes and prints a one-screen triage report for developers.
        </p>

        <div className="actions">
          <button type="button" onClick={runGatewayDiagnostics} disabled={busy || diagnosticsRunning}>
            {diagnosticsRunning ? 'Running diagnostics ...' : 'Run Diagnostics'}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={copyDiagnosticsReport}
            disabled={diagnosticsRunning || !diagnosticsReport}
          >
            Copy Report
          </button>
          <button
            type="button"
            className="secondary"
            onClick={clearDiagnosticsReport}
            disabled={diagnosticsRunning || !diagnosticsReport}
          >
            Clear Report
          </button>
        </div>

        {diagnosticsReport ? (
          <div className="diagnostics-box">
            <div>
              <strong>Generated:</strong> <code>{diagnosticsGeneratedAt}</code>
            </div>
            <pre className="diagnostics-report">{diagnosticsReport}</pre>
          </div>
        ) : (
          <small>
            Report includes status codes for <code>/health</code>, <code>/graphql</code>, and auth endpoints with
            triage guidance.
          </small>
        )}
      </section>

      <section className={`status ${statusType}`}>
        {statusText}
      </section>
    </div>
  );
}
