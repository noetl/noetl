# Gateway React Amadeus Example

Very small React starter UI for developers who want to integrate their applications with NoETL Gateway.

This example focuses on three flows:

1. Login against Gateway (`/api/auth/login` or `/api/auth/validate`)
2. Execute the Amadeus playbook via GraphQL (`executePlaybook`) with async callback routing
3. Run built-in Gateway diagnostics (`/health`, GraphQL auth, auth endpoint probes) and produce a one-screen triage report

The existing `tests/fixtures/gateway_ui` files are not used or modified.

## Default target

This app is preconfigured to call:

- `https://gateway.mestumre.dev`

You can override it via UI input or environment variable.
For local development, Vite also proxies API paths to this target to avoid browser CORS blocks.

## Files

- `src/App.jsx` - main UI and Gateway integration logic
- `src/main.jsx` - React entry point
- `src/styles.css` - minimal styles
- `vite.config.js` - local dev server on port `8080`
- `login.html` - Auth0 callback entry page for local development
- `.env.example` - endpoint/playbook defaults

## Prerequisites

1. Gateway is reachable at `https://gateway.mestumre.dev`
2. Auth playbooks are configured on that Gateway deployment
3. `api_integration/amadeus_ai_api` playbook is registered and runnable
4. Auth0 SPA app has callback URL for this UI

## Auth0 callback setup (required)

In your Auth0 application settings, include:

- `http://localhost:8080/login.html` in **Allowed Callback URLs**
- `http://localhost:8080/` in **Allowed Logout URLs**
- `http://localhost:8080` in **Allowed Web Origins**
- `Authorization Code` grant enabled (PKCE flow)

If you host this example elsewhere, add that URL as well.

This example uses Auth0 SPA SDK redirect login (code flow), not the old implicit `id_token token` flow.

## Troubleshooting Auth0 "Oops, something went wrong"

If you are redirected to an Auth0 error page:

1. Verify this is a **Single Page Application** in Auth0.
2. Verify `client_id` belongs to tenant `mestumre-development.us.auth0.com`.
3. Verify these exact values in Auth0 app settings:
   - Allowed Callback URLs: `http://localhost:8080/login.html`
   - Allowed Logout URLs: `http://localhost:8080/`
   - Allowed Web Origins: `http://localhost:8080`
4. Verify application grant type includes **Authorization Code**.
5. Open Auth0 tenant logs for the failed login attempt to see the exact error code/reason.

If Auth0 says `Callback URL mismatch` for `http://localhost:3001/`, run this example on the default `8080` port or allowlist `http://localhost:3001/`.
If the local app buttons look disabled after returning from Auth0 error page, reload `http://localhost:8080` once.

## Troubleshooting CORS on localhost

If browser console shows a CORS error for `https://gateway.mestumre.dev/api/...` from `http://localhost:8080`:

1. Restart `npm run dev` so Vite proxy config is active.
2. Keep `VITE_USE_DEV_PROXY=true` (default).
3. Call API paths as relative URLs (`/api`, `/graphql`, `/noetl`) through the app.

When proxy is enabled, browser requests stay same-origin (`localhost:8080`) and Vite forwards them to gateway.

## Troubleshooting 502 from `/api/auth/login` on localhost

If browser shows `POST http://localhost:8080/api/auth/login 502 (Bad Gateway)`:

1. Check Vite terminal output for:
   - `Proxy target: ...`
   - `Proxy error for ...`
2. Confirm target health directly:
   - `curl -i -X POST https://gateway.mestumre.dev/api/auth/login -H 'Content-Type: application/json' --data '{}'`
   - expected result is `422` (missing `auth0_token`), not `502`
3. Restart local dev server after any config/env changes.

This fixture auto-guards against proxy loops (for example `VITE_GATEWAY_URL=http://localhost:8080`) and falls back to `https://gateway.mestumre.dev`.

## Run locally

```bash
cd tests/fixtures/gateway_react_amadeus_example
npm install
npm run dev
```

Open:

- `http://localhost:8080`

## Login options in the UI

- **Recommended: Login with Auth0 (redirect)**:
  - Click `Login with Auth0 (redirect)`
  - Complete Auth0 Universal Login
  - UI handles callback and creates Gateway session automatically
- **Manual Auth0 token login** (fallback/debug):
  - Paste Auth0 ID token (JWT)
  - Click `Login via /api/auth/login`
- **Existing session token**:
  - Paste session token
  - Click `Validate via /api/auth/validate`

## Run Amadeus playbook

1. Keep playbook path as `api_integration/amadeus_ai_api` (or adjust)
2. Enter travel query
3. Click `Run executePlaybook`

The app will:

- open SSE channel at `GET /events?session_token=...`
- call `POST /graphql` with `executePlaybook` + `clientId` for async callback routing
- wait for `playbook/result` callback and display returned payload
- if callback does not arrive quickly, poll `GET /noetl/executions/{executionId}` in parallel
- if execution reaches terminal state first, immediately switch to polling-derived output (no need to wait for callback timeout)
- extract final response text from execution events and show:
  - `Playbook Response` (human-readable text)
  - full payload JSON in execution details

## Callback + fallback behavior (important)

Gateway async callback delivery depends on an active SSE client connection tied to `clientId`.

If the worker sends callback while SSE client is disconnected, Gateway may return:

- `202` with payload like `{ "status": "queued", "clientDisconnected": true }`

This means:

- playbook execution can still be `COMPLETED`
- callback event is not delivered to browser in real time
- UI must recover from execution events (polling path)

This example now does that recovery automatically.

## Troubleshooting: "Execution started. Waiting callback ...", but no response appears

1. Check session panel:
   - `Callback channel` should ideally be `connected`
   - `Callback client` should show a non-empty client id
2. Keep the tab open during execution. Reloading or navigating away can drop SSE.
3. Run Gateway diagnostics from the UI to verify routing/auth guards.
4. Inspect execution events directly:

```bash
curl -sS \
  -H "Authorization: Bearer <session_token>" \
  "https://gateway.mestumre.dev/noetl/executions/<execution_id>?page=1&page_size=200" | jq '.events[] | select(.node_name=="send_callback") | {event_id,event_type,status,result}'
```

If `send_callback` shows `clientDisconnected: true`, real-time callback was not deliverable at that moment.

5. Inspect extracted response payload in events:

```bash
curl -sS \
  -H "Authorization: Bearer <session_token>" \
  "https://gateway.mestumre.dev/noetl/executions/<execution_id>?page=1&page_size=200" | jq '.events[] | select(.node_name=="extract_summary" and .event_type=="command.completed") | .result'
```

The UI fallback reads this event data and renders it as `Playbook Response`.

## Environment variables

Copy `.env.example` to `.env` and edit if needed:

```bash
cp .env.example .env
```

Variables:

- `VITE_GATEWAY_URL`
- `VITE_AUTH0_DOMAIN`
- `VITE_AUTH0_CLIENT_ID`
- `VITE_AUTH0_REDIRECT_URI` (optional; defaults to `http://localhost:8080/login.html` on localhost)
- `VITE_USE_DEV_PROXY` (optional; default `true` on localhost)
- `VITE_AMADEUS_PLAYBOOK_PATH`
