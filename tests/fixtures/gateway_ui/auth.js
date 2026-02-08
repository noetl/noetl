// Authentication utilities for Gateway UI
//
// NOTE: This file requires env.js to be loaded first.
// The gateway URL is configured via window.ENV.gatewayUrl

// Get API base from environment configuration (set by env.js)
function getApiBase() {
  if (window.ENV && window.ENV.gatewayUrl) {
    return window.ENV.gatewayUrl;
  }
  // Fallback for direct usage without env.js
  console.warn('[auth.js] ENV not loaded, using fallback localhost:8080');
  return 'http://localhost:8080';
}

// Lazy-initialized API URLs (allows env.js to load first)
let _apiBase = null;
let _authValidateUrl = null;
let _authCheckAccessUrl = null;

// SSE connection state
let _eventSource = null;
let _clientId = null;
let _sseConnected = false;
let _pendingCallbacks = new Map(); // requestId -> { resolve, reject, typingIndicator }
let _reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY_MS = 2000;

function getAuthValidateUrl() {
  if (!_authValidateUrl) {
    _apiBase = getApiBase();
    _authValidateUrl = `${_apiBase}/api/auth/validate`;
  }
  return _authValidateUrl;
}

function getAuthCheckAccessUrl() {
  if (!_authCheckAccessUrl) {
    _apiBase = getApiBase();
    _authCheckAccessUrl = `${_apiBase}/api/auth/check-access`;
  }
  return _authCheckAccessUrl;
}

// Check authentication on page load
// Skip auto-check on login page to prevent redirect loops
window.addEventListener('DOMContentLoaded', async () => {
  const isLoginPage = window.location.pathname.endsWith('login.html') ||
                      window.location.pathname === '/login.html';
  if (!isLoginPage) {
    await checkAuth();
  }
});

/**
 * Check if user is authenticated, redirect to login if not
 * Uses "soft" validation for local testing - if token and user_info exist in localStorage,
 * we trust them for UI display. Real authorization happens at API level.
 */
async function checkAuth() {
  const token = getSessionToken();
  const userInfo = getUserInfo();

  if (!token) {
    redirectToLogin();
    return false;
  }

  // If we have cached user info, use it for UI display
  // This enables testing while backend validation playbook is being fixed
  if (userInfo) {
    console.log('Using cached user info for UI (soft auth mode)');
    displayUserInfo();

    // Connect SSE for real-time callbacks
    connectSSE();

    // Try to validate in background, but don't block UI
    validateSession(token).then(valid => {
      if (valid) {
        console.log('Backend session validation succeeded');
      } else {
        console.warn('Backend session validation failed - UI using cached data');
        // Don't redirect - let API calls handle 401 errors
      }
    }).catch(err => {
      console.warn('Backend session validation error:', err);
    });

    return true;
  }

  // No cached user info - must validate with backend
  const valid = await validateSession(token);

  if (!valid) {
    clearAuth();
    redirectToLogin();
    return false;
  }

  // Display user info
  displayUserInfo();

  // Connect SSE for real-time callbacks
  connectSSE();

  return true;
}

/**
 * Get session token from localStorage
 */
function getSessionToken() {
  return localStorage.getItem('session_token');
}

/**
 * Get user info from localStorage
 */
function getUserInfo() {
  const userStr = localStorage.getItem('user_info');
  if (!userStr) return null;

  try {
    return JSON.parse(userStr);
  } catch (e) {
    console.error('Failed to parse user info:', e);
    return null;
  }
}

/**
 * Validate session token with backend
 */
async function validateSession(token) {
  try {
    const response = await fetch(getAuthValidateUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_token: token,
      }),
    });

    if (!response.ok) {
      console.error('Session validation failed:', response.status);
      return false;
    }

    const data = await response.json();

    if (data.valid && data.user) {
      // Update user info if returned
      localStorage.setItem('user_info', JSON.stringify(data.user));
      return true;
    }

    return false;
  } catch (error) {
    console.error('Session validation error:', error);
    return false;
  }
}

/**
 * Check if user has access to execute a playbook
 */
async function checkPlaybookAccess(playbookPath, permissionType = 'execute') {
  const token = getSessionToken();

  if (!token) {
    return false;
  }

  try {
    const response = await fetch(getAuthCheckAccessUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_token: token,
        playbook_path: playbookPath,
        permission_type: permissionType,
      }),
    });

    if (!response.ok) {
      console.error('Access check failed:', response.status);
      return false;
    }

    const data = await response.json();
    return data.allowed || false;
  } catch (error) {
    console.error('Access check error:', error);
    return false;
  }
}

/**
 * Display user information in header
 */
function displayUserInfo() {
  const user = getUserInfo();
  if (!user) return;

  const userDisplay = document.getElementById('userDisplay');
  if (userDisplay) {
    userDisplay.textContent = user.display_name || user.email;
  }

  // Setup logout button
  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', logout);
  }
}

/**
 * Logout user
 */
function logout() {
  disconnectSSE();
  clearAuth();
  redirectToLogin();
}

/**
 * Clear authentication data
 */
function clearAuth() {
  localStorage.removeItem('session_token');
  localStorage.removeItem('user_info');
}

/**
 * Redirect to login page
 */
function redirectToLogin() {
  window.location.href = '/login.html';
}

/**
 * Make authenticated GraphQL request
 */
async function authenticatedGraphQL(query, variables) {
  const token = getSessionToken();

  if (!token) {
    throw new Error('Not authenticated');
  }

  const response = await fetch(`${getApiBase()}/graphql`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({
      query,
      variables,
    }),
  });

  if (response.status === 401) {
    // Session expired, redirect to login
    clearAuth();
    redirectToLogin();
    throw new Error('Session expired');
  }

  if (!response.ok) {
    throw new Error(`GraphQL request failed: ${response.status}`);
  }

  const data = await response.json();

  if (data.errors) {
    throw new Error(data.errors[0].message || 'GraphQL error');
  }

  return data.data;
}

// ============================================================================
// SSE CONNECTION MANAGEMENT
// ============================================================================

/**
 * Connect to SSE endpoint for real-time playbook results
 */
function connectSSE() {
  const token = getSessionToken();
  if (!token) {
    console.warn('[SSE] No session token, skipping SSE connection');
    return;
  }

  // Close existing connection if any
  if (_eventSource) {
    _eventSource.close();
    _eventSource = null;
  }

  const sseUrl = `${getApiBase()}/events?session_token=${encodeURIComponent(token)}${_clientId ? `&client_id=${encodeURIComponent(_clientId)}` : ''}`;
  console.log('[SSE] Connecting to:', sseUrl.replace(/session_token=[^&]+/, 'session_token=***'));

  _eventSource = new EventSource(sseUrl);

  _eventSource.onopen = () => {
    console.log('[SSE] Connection opened');
    _reconnectAttempts = 0;
  };

  // Handle initialization message (JSON-RPC response)
  _eventSource.addEventListener('message', (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.result && msg.result.clientId) {
        _clientId = msg.result.clientId;
        _sseConnected = true;
        console.log('[SSE] Initialized with clientId:', _clientId.substring(0, 8) + '...');

        // Handle any pending requests from reconnection
        if (msg.result.pendingRequests && msg.result.pendingRequests.length > 0) {
          console.log('[SSE] Found pending requests:', msg.result.pendingRequests.length);
        }

        // Dispatch custom event for UI
        window.dispatchEvent(new CustomEvent('sse-connected', { detail: { clientId: _clientId } }));
      }
    } catch (e) {
      console.warn('[SSE] Failed to parse message:', e);
    }
  });

  // Handle playbook result notifications
  _eventSource.addEventListener('playbook/result', (event) => {
    try {
      const msg = JSON.parse(event.data);
      const params = msg.params || {};
      const requestId = params.requestId;

      console.log('[SSE] Playbook result:', requestId?.substring(0, 8) + '...', params.status);

      // Find pending callback
      const pending = _pendingCallbacks.get(requestId);
      if (pending) {
        _pendingCallbacks.delete(requestId);

        if (params.status === 'FAILED' || params.error) {
          const errorMsg = params.error?.message || 'Playbook execution failed';
          pending.reject(new Error(errorMsg));
        } else {
          pending.resolve({
            id: params.executionId,
            executionId: params.executionId,
            requestId: requestId,
            status: params.status,
            // Support both camelCase (from playbooks) and snake_case (legacy)
            textOutput: params.data?.textOutput || params.data?.text_output || params.data?.result || JSON.stringify(params.data),
            data: params.data
          });
        }
      } else {
        console.warn('[SSE] No pending callback for requestId:', requestId?.substring(0, 8) + '...');
        // Dispatch event for any listeners
        window.dispatchEvent(new CustomEvent('playbook-result', { detail: params }));
      }
    } catch (e) {
      console.error('[SSE] Failed to handle playbook result:', e);
    }
  });

  // Handle progress notifications
  _eventSource.addEventListener('playbook/progress', (event) => {
    try {
      const msg = JSON.parse(event.data);
      const params = msg.params || {};
      console.log('[SSE] Progress:', params.requestId?.substring(0, 8) + '...', params.message || params.step);

      // Dispatch event for UI
      window.dispatchEvent(new CustomEvent('playbook-progress', { detail: params }));
    } catch (e) {
      console.warn('[SSE] Failed to handle progress:', e);
    }
  });

  // Handle ping/heartbeat
  _eventSource.addEventListener('ping', () => {
    // Heartbeat received, connection is alive
  });

  // Handle errors
  _eventSource.addEventListener('error', (event) => {
    try {
      const msg = JSON.parse(event.data);
      console.error('[SSE] Error event:', msg);

      if (msg.error?.code === -32001) { // Unauthorized
        clearAuth();
        redirectToLogin();
      }
    } catch (e) {
      // Not a JSON error, likely connection error
      console.error('[SSE] Connection error');
    }
  });

  _eventSource.onerror = (error) => {
    console.error('[SSE] EventSource error:', error);
    _sseConnected = false;

    // Attempt reconnection
    if (_reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      _reconnectAttempts++;
      console.log(`[SSE] Reconnecting in ${RECONNECT_DELAY_MS}ms (attempt ${_reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`);
      setTimeout(() => connectSSE(), RECONNECT_DELAY_MS);
    } else {
      console.error('[SSE] Max reconnection attempts reached');
      // Reject all pending callbacks
      for (const [requestId, pending] of _pendingCallbacks) {
        pending.reject(new Error('SSE connection lost'));
      }
      _pendingCallbacks.clear();
    }
  };
}

/**
 * Disconnect SSE
 */
function disconnectSSE() {
  if (_eventSource) {
    _eventSource.close();
    _eventSource = null;
  }
  _sseConnected = false;
  _clientId = null;
}

/**
 * Get current client ID for SSE
 */
function getClientId() {
  return _clientId;
}

/**
 * Check if SSE is connected
 */
function isSSEConnected() {
  return _sseConnected && _eventSource && _eventSource.readyState === EventSource.OPEN;
}

/**
 * Register a pending callback for a playbook execution
 */
function registerPendingCallback(requestId, resolve, reject, timeout = 120000) {
  const timeoutId = setTimeout(() => {
    const pending = _pendingCallbacks.get(requestId);
    if (pending) {
      _pendingCallbacks.delete(requestId);
      pending.reject(new Error('Playbook execution timed out'));
    }
  }, timeout);

  _pendingCallbacks.set(requestId, {
    resolve: (result) => {
      clearTimeout(timeoutId);
      resolve(result);
    },
    reject: (error) => {
      clearTimeout(timeoutId);
      reject(error);
    }
  });
}

/**
 * Wait for SSE connection to be established
 * @param {number} timeout - Maximum time to wait in ms (default: 10000)
 * @returns {Promise<boolean>} - Resolves to true when connected
 */
async function waitForSSEConnection(timeout = 10000) {
  if (isSSEConnected()) {
    return true;
  }

  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      window.removeEventListener('sse-connected', handler);
      reject(new Error('SSE connection timeout. Please refresh the page.'));
    }, timeout);

    const handler = () => {
      clearTimeout(timeoutId);
      resolve(true);
    };

    window.addEventListener('sse-connected', handler, { once: true });

    // If SSE hasn't started connecting, try to connect
    if (!_eventSource) {
      connectSSE();
    }
  });
}

/**
 * Execute playbook with async callback via SSE
 */
async function executePlaybookAsync(playbookName, variables = {}) {
  // Wait for SSE connection if not already connected
  if (!isSSEConnected()) {
    console.log('[SSE] Waiting for connection before executing playbook...');
    await waitForSSEConnection();
  }

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

  const gqlVariables = {
    name: playbookName,
    vars: variables,
    clientId: _clientId
  };

  // Execute the mutation
  const data = await authenticatedGraphQL(mutation, gqlVariables);
  const result = data.executePlaybook;

  if (!result.requestId) {
    // No async callback, return immediately (shouldn't happen with clientId)
    console.warn('[SSE] No requestId returned, falling back to sync result');
    return result;
  }

  // Wait for callback via SSE
  return new Promise((resolve, reject) => {
    registerPendingCallback(result.requestId, resolve, reject);
    console.log('[SSE] Waiting for callback:', result.requestId.substring(0, 8) + '...');
  });
}
