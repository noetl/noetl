import { resolveGatewayBaseUrl } from "./gatewayBaseUrl";

export type GatewayUser = {
  email?: string;
  display_name?: string;
  name?: string;
  roles?: string[];
  [key: string]: unknown;
};

type ExecutePlaybookAsyncResult = {
  id?: string;
  executionId?: string;
  requestId?: string;
  status?: string;
  textOutput?: string;
  data?: Record<string, unknown>;
};

type PendingCallback = {
  resolve: (value: ExecutePlaybookAsyncResult) => void;
  reject: (error: Error) => void;
  timeoutId: number;
};

const SESSION_TOKEN_KEY = "session_token";
const USER_INFO_KEY = "user_info";
const PLAYBOOK_NAME = "api_integration/amadeus_ai_api";

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY_MS = 2000;
const CALLBACK_TIMEOUT_MS = 120000;

let eventSource: EventSource | null = null;
let clientId: string | null = null;
let sseConnected = false;
let reconnectAttempts = 0;

const pendingCallbacks = new Map<string, PendingCallback>();
const progressListeners = new Set<(message: string) => void>();
const connectionListeners = new Set<(connected: boolean) => void>();

function notifyProgress(message: string): void {
  progressListeners.forEach((listener) => listener(message));
}

function notifyConnection(connected: boolean): void {
  connectionListeners.forEach((listener) => listener(connected));
}

function getGatewayBaseUrl(): string {
  return resolveGatewayBaseUrl();
}

function getAuth0RedirectUri(): string {
  return (
    import.meta.env.VITE_AUTH0_REDIRECT_URI ||
    `${window.location.origin}/login`
  );
}

export function getAuth0Domain(): string {
  return import.meta.env.VITE_AUTH0_DOMAIN || "mestumre-development.us.auth0.com";
}

export function getAuth0ClientId(): string {
  return import.meta.env.VITE_AUTH0_CLIENT_ID || "Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN";
}

export function getAuth0AuthorizeUrl(): string {
  const nonce = Math.random().toString(36).slice(2);
  const domain = getAuth0Domain();
  const clientIdValue = getAuth0ClientId();
  const redirectUri = getAuth0RedirectUri();

  return (
    `https://${domain}/authorize?` +
    `response_type=id_token token&` +
    `client_id=${encodeURIComponent(clientIdValue)}&` +
    `redirect_uri=${encodeURIComponent(redirectUri)}&` +
    `scope=openid profile email&` +
    `nonce=${encodeURIComponent(nonce)}`
  );
}

function getSessionToken(): string | null {
  return localStorage.getItem(SESSION_TOKEN_KEY);
}

function setSessionToken(token: string): void {
  localStorage.setItem(SESSION_TOKEN_KEY, token);
}

function setUserInfo(user: GatewayUser): void {
  localStorage.setItem(USER_INFO_KEY, JSON.stringify(user));
}

function clearAuthStorage(): void {
  localStorage.removeItem(SESSION_TOKEN_KEY);
  localStorage.removeItem(USER_INFO_KEY);
}

export function getUserInfo(): GatewayUser | null {
  const value = localStorage.getItem(USER_INFO_KEY);
  if (!value) {
    return null;
  }
  try {
    return JSON.parse(value) as GatewayUser;
  } catch {
    return null;
  }
}

export async function validateSession(token?: string): Promise<boolean> {
  const sessionToken = token || getSessionToken();
  if (!sessionToken) {
    return false;
  }

  const response = await fetch(`${getGatewayBaseUrl()}/api/auth/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_token: sessionToken }),
  });

  if (!response.ok) {
    return false;
  }

  const data = (await response.json()) as { valid?: boolean; user?: GatewayUser };
  if (data.valid) {
    setSessionToken(sessionToken);
    if (data.user) {
      setUserInfo(data.user);
    }
    return true;
  }
  return false;
}

export async function loginWithAuth0Token(idToken: string): Promise<void> {
  const gatewayBaseUrl = getGatewayBaseUrl();
  const response = await fetch(`${gatewayBaseUrl}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      auth0_token: idToken,
      auth0_domain: getAuth0Domain(),
    }),
  });

  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail =
        payload?.error ||
        payload?.message ||
        JSON.stringify(payload);
    } catch {
      try {
        detail = (await response.text()).slice(0, 300);
      } catch {
        detail = "";
      }
    }
    const message = detail
      ? `Auth login failed (${response.status}) via ${gatewayBaseUrl}: ${detail}`
      : `Auth login failed (${response.status}) via ${gatewayBaseUrl}`;
    throw new Error(message);
  }

  const data = (await response.json()) as { session_token?: string; user?: GatewayUser };
  if (!data.session_token) {
    throw new Error("No session token returned from gateway");
  }

  setSessionToken(data.session_token);
  if (data.user) {
    setUserInfo(data.user);
  }
}

export function logout(): void {
  disconnectSSE();
  clearAuthStorage();
}

export function isAuthenticated(): boolean {
  return Boolean(getSessionToken());
}

export async function checkPlaybookAccess(
  playbookPath: string,
  permissionType = "execute",
): Promise<boolean> {
  const token = getSessionToken();
  if (!token) {
    return false;
  }

  const response = await fetch(`${getGatewayBaseUrl()}/api/auth/check-access`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_token: token,
      playbook_path: playbookPath,
      permission_type: permissionType,
    }),
  });

  if (!response.ok) {
    return false;
  }

  const data = (await response.json()) as { allowed?: boolean };
  return Boolean(data.allowed);
}

async function authenticatedGraphQL(query: string, variables: Record<string, unknown>): Promise<any> {
  const token = getSessionToken();
  if (!token) {
    throw new Error("Not authenticated");
  }

  const response = await fetch(`${getGatewayBaseUrl()}/graphql`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query, variables }),
  });

  if (response.status === 401) {
    logout();
    throw new Error("Session expired");
  }
  if (!response.ok) {
    throw new Error(`GraphQL request failed (${response.status})`);
  }

  const body = await response.json();
  if (body.errors?.length) {
    throw new Error(body.errors[0].message || "GraphQL error");
  }
  return body.data;
}

function registerPendingCallback(
  requestId: string,
  resolve: (value: ExecutePlaybookAsyncResult) => void,
  reject: (error: Error) => void,
): void {
  const timeoutId = window.setTimeout(() => {
    const pending = pendingCallbacks.get(requestId);
    if (!pending) {
      return;
    }
    pendingCallbacks.delete(requestId);
    pending.reject(new Error("Playbook callback timed out"));
  }, CALLBACK_TIMEOUT_MS);

  pendingCallbacks.set(requestId, { resolve, reject, timeoutId });
}

function handlePlaybookResult(message: any): void {
  const params = message?.params || {};
  const requestId = params.requestId as string | undefined;
  if (!requestId) {
    return;
  }

  const pending = pendingCallbacks.get(requestId);
  if (!pending) {
    return;
  }

  pendingCallbacks.delete(requestId);
  window.clearTimeout(pending.timeoutId);

  if (params.status === "FAILED" || params.error) {
    pending.reject(new Error(params.error?.message || "Playbook execution failed"));
    return;
  }

  pending.resolve({
    id: params.executionId,
    executionId: params.executionId,
    requestId,
    status: params.status,
    textOutput:
      params.data?.textOutput ||
      params.data?.text_output ||
      params.data?.summary ||
      params.data?.result ||
      JSON.stringify(params.data || {}),
    data: params.data || {},
  });
}

function connectSSEInternal(): void {
  const token = getSessionToken();
  if (!token) {
    return;
  }

  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  const url =
    `${getGatewayBaseUrl()}/events?session_token=${encodeURIComponent(token)}` +
    (clientId ? `&client_id=${encodeURIComponent(clientId)}` : "");

  eventSource = new EventSource(url);

  eventSource.onopen = () => {
    reconnectAttempts = 0;
  };

  eventSource.addEventListener("message", (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message?.result?.clientId) {
        clientId = message.result.clientId;
        sseConnected = true;
        notifyConnection(true);
      }
    } catch {
      // Ignore malformed payloads from heartbeat noise.
    }
  });

  eventSource.addEventListener("playbook/result", (event) => {
    try {
      handlePlaybookResult(JSON.parse(event.data));
    } catch {
      // ignore
    }
  });

  eventSource.addEventListener("playbook/progress", (event) => {
    try {
      const message = JSON.parse(event.data);
      const params = message?.params || {};
      notifyProgress(params.message || params.step || "Processing...");
    } catch {
      // ignore
    }
  });

  eventSource.onerror = () => {
    sseConnected = false;
    notifyConnection(false);
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      pendingCallbacks.forEach((pending) => {
        window.clearTimeout(pending.timeoutId);
        pending.reject(new Error("SSE connection lost"));
      });
      pendingCallbacks.clear();
      return;
    }
    reconnectAttempts += 1;
    window.setTimeout(connectSSEInternal, RECONNECT_DELAY_MS);
  };
}

export function connectSSE(): void {
  connectSSEInternal();
}

export function disconnectSSE(): void {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  sseConnected = false;
  notifyConnection(false);
}

export function subscribeProgress(listener: (message: string) => void): () => void {
  progressListeners.add(listener);
  return () => {
    progressListeners.delete(listener);
  };
}

export function subscribeConnection(listener: (connected: boolean) => void): () => void {
  connectionListeners.add(listener);
  return () => {
    connectionListeners.delete(listener);
  };
}

export function isSSEConnected(): boolean {
  return (
    sseConnected &&
    eventSource !== null &&
    eventSource.readyState === EventSource.OPEN
  );
}

export async function waitForSSEConnection(timeoutMs = 10000): Promise<void> {
  if (isSSEConnected()) {
    return;
  }

  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      unsubscribe();
      reject(new Error("SSE connection timeout"));
    }, timeoutMs);

    const unsubscribe = subscribeConnection((connected) => {
      if (!connected) {
        return;
      }
      window.clearTimeout(timeoutId);
      unsubscribe();
      resolve();
    });

    connectSSE();
  });
}

export async function executeGatewayPlaybook(query: string): Promise<ExecutePlaybookAsyncResult> {
  const hasAccess = await checkPlaybookAccess(PLAYBOOK_NAME, "execute");
  if (!hasAccess) {
    throw new Error("You do not have permission to execute this playbook");
  }

  await waitForSSEConnection();

  const mutation = `
    mutation ExecutePlaybook($name: String!, $vars: JSON, $clientId: String) {
      executePlaybook(name: $name, variables: $vars, clientId: $clientId) {
        id
        executionId
        requestId
        name
        status
      }
    }
  `;

  const result = await authenticatedGraphQL(mutation, {
    name: PLAYBOOK_NAME,
    vars: { query },
    clientId,
  });

  const execution = result.executePlaybook as ExecutePlaybookAsyncResult;
  if (!execution.requestId) {
    return execution;
  }

  return new Promise((resolve, reject) => {
    registerPendingCallback(execution.requestId as string, resolve, reject);
  });
}

export async function executePlaybook(
  playbookName: string,
  variables: Record<string, unknown>,
): Promise<ExecutePlaybookAsyncResult> {
  const hasAccess = await checkPlaybookAccess(playbookName, "execute");
  if (!hasAccess) {
    throw new Error("You do not have permission to execute this playbook");
  }

  await waitForSSEConnection();

  const mutation = `
    mutation ExecutePlaybook($name: String!, $vars: JSON, $clientId: String) {
      executePlaybook(name: $name, variables: $vars, clientId: $clientId) {
        id
        executionId
        requestId
        name
        status
      }
    }
  `;

  const result = await authenticatedGraphQL(mutation, {
    name: playbookName,
    vars: variables,
    clientId,
  });

  const execution = result.executePlaybook as ExecutePlaybookAsyncResult;
  if (!execution.requestId) {
    return execution;
  }

  return new Promise((resolve, reject) => {
    registerPendingCallback(execution.requestId as string, resolve, reject);
  });
}
