// Authentication utilities for Gateway UI

// For local testing, point to the gateway URL
// const API_BASE = window.location.origin;
const API_BASE = 'https://gateway.mestumre.dev';
const AUTH_VALIDATE_URL = `${API_BASE}/api/auth/validate`;
const AUTH_CHECK_ACCESS_URL = `${API_BASE}/api/auth/check-access`;

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
    const response = await fetch(AUTH_VALIDATE_URL, {
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
    const response = await fetch(AUTH_CHECK_ACCESS_URL, {
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

  const response = await fetch(`${API_BASE}/graphql`, {
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
