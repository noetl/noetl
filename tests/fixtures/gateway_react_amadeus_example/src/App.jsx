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
  const [diagnosticsRunning, setDiagnosticsRunning] = useState(false);
  const [diagnosticsGeneratedAt, setDiagnosticsGeneratedAt] = useState('');
  const [diagnosticsReport, setDiagnosticsReport] = useState('');
  const callbackHandledRef = useRef(false);
  const auth0ClientRef = useRef(null);

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
    localStorage.removeItem(STORAGE_TOKEN_KEY);
    localStorage.removeItem(STORAGE_USER_KEY);
    setSessionToken('');
    setSessionTokenInput('');
    setUser(null);
    setExecutionId('');
    setExecutionStatus('');
    setExecutionSummary(null);
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
        return probe.status === 200;
      case 'graphql_auth':
        return probe.status === 401 || probe.status === 403;
      case 'auth_login_schema':
        return probe.status === 400 || probe.status === 401 || probe.status === 422;
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
    const authProbes = [byId.auth_login_schema, byId.auth_validate_dummy, byId.auth_check_access_dummy].filter(
      Boolean
    );
    const authHas502 = authProbes.some((probe) => probe.status === 502);
    const networkErrors = probes.filter((probe) => probe.status === 0);

    const triage = [];
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

  async function pollExecution(execId, token) {
    const terminalStatuses = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);

    for (let attempt = 0; attempt < 90; attempt += 1) {
      try {
        const data = await request(`/noetl/executions/${execId}?page=1&page_size=50`, {
          method: 'GET',
          token,
        });

        const nextStatus = (data.status || '').toUpperCase();
        setExecutionStatus(nextStatus || 'UNKNOWN');

        if (terminalStatuses.has(nextStatus)) {
          const failedEvent = (data.events || []).find(
            (event) => event.status === 'FAILED' || Boolean(event.error)
          );

          setExecutionSummary({
            status: nextStatus,
            playbook_path: data.path,
            event_count: data.pagination?.total_events,
            end_time: data.end_time,
            latest_error: failedEvent?.error || null,
          });

          if (nextStatus === 'COMPLETED') {
            setStatus(`Execution ${execId} completed.`, 'success');
          } else {
            setStatus(`Execution ${execId} finished with ${nextStatus}.`, 'error');
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
    setStatus('Starting playbook via /graphql executePlaybook ...', 'info');

    const mutation = `
      mutation ExecuteAmadeus($name: String!, $variables: JSON) {
        executePlaybook(name: $name, variables: $variables) {
          id
          executionId
          status
          requestId
          name
        }
      }
    `;

    try {
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
      setStatus(`Execution ${execId} started. Polling status ...`, 'info');

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
            {executionSummary ? (
              <pre>{JSON.stringify(executionSummary, null, 2)}</pre>
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
