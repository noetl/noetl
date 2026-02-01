# Gateway Async Callback Architecture

This document describes the asynchronous callback system for the NoETL Gateway, enabling real-time playbook result delivery to UI clients via SSE (Server-Sent Events) and WebSocket transports.

## Implementation Progress

### Phase 1: SSE Transport (Current)
- [x] Create `connection_hub.rs` module
- [x] Create `request_store.rs` module (NATS K/V)
- [x] Add SSE endpoint (`GET /events`)
- [x] Add callback endpoints (`POST /api/internal/callback/async`, `POST /api/internal/progress`)
- [x] Add configuration for transport settings
- [x] Update `executePlaybook` GraphQL mutation to use async callbacks (pass request_id, client_id)
- [x] Update playbooks to send HTTP callbacks (amadeus_ai_api.yaml)
- [x] Update UI to use SSE for results (auth.js, app.js)
- [x] Test end-to-end flow (gateway deployed, UI changes ready)
- [x] Documentation

### Phase 2: WebSocket Transport
- [ ] Add WebSocket endpoint (`GET /ws`)
- [ ] Implement bidirectional messaging
- [ ] Add WebSocket to ConnectionHub
- [ ] Update UI to support WebSocket option
- [ ] Configuration for transport selection

### Phase 3: Production Hardening
- [x] Reconnection handling with request recovery (pending requests returned on reconnect)
- [x] Multiple clients per session support (session_clients mapping)
- [x] Heartbeat/keepalive mechanism (ping notifications)
- [ ] Metrics and monitoring
- [ ] Load testing

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                   Gateway                                        │
│                                                                                  │
│  ┌────────────────┐   ┌──────────────────┐   ┌─────────────────────────────┐   │
│  │ ConnectionHub  │   │  RequestStore    │   │   CallbackRouter            │   │
│  │                │   │  (NATS K/V)      │   │                             │   │
│  │ client_id →    │◄──│                  │◄──│ POST /api/internal/callback │   │
│  │ [connections]  │   │ request_id →     │   │                             │   │
│  │                │   │ {client_id,      │   │ Receives from workers       │   │
│  │ Supports:      │   │  session_token,  │   │ Looks up client_id          │   │
│  │ - SSE          │   │  execution_id}   │   │ Routes via ConnectionHub    │   │
│  │ - WebSocket    │   │                  │   │                             │   │
│  └────────────────┘   └──────────────────┘   └─────────────────────────────┘   │
│         ▲                     ▲                           │                     │
│         │                     │                           │                     │
│    ┌────┴────┐          ┌─────┴─────┐                     │                     │
│    │         │          │           │                     ▼                     │
│  ┌─┴───────┐ │    ┌─────┴────┐ ┌────┴────┐         Lookup & Route              │
│  │GET      │ │    │ GraphQL  │ │  REST   │         to client                   │
│  │/events  │ │    │ mutation │ │  API    │                                     │
│  │(SSE)    │ │    │          │ │         │                                     │
│  └─────────┘ │    └──────────┘ └─────────┘                                     │
│              │                                                                  │
│  ┌───────────┴┐                                                                │
│  │GET /ws     │                                                                │
│  │(WebSocket) │                                                                │
│  └────────────┘                                                                │
└─────────────────────────────────────────────────────────────────────────────────┘
          │                              │
          │ SSE/WS Connection            │ HTTP Callback
          ▼                              │
     ┌─────────┐                         │
     │   UI    │                         │
     │ Client  │                         │
     └─────────┘                         │
                                         ▼
                              ┌────────────────────┐
                              │   NoETL Worker     │
                              │                    │
                              │ Executes playbook  │
                              │ Sends callback     │
                              └────────────────────┘
```

## Message Format (MCP-Compatible JSON-RPC 2.0)

Following the [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2025-11-25), all messages use JSON-RPC 2.0 format for consistency and interoperability.

### Connection Initialization

**Client → Server (SSE/WS connect):**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "clientInfo": {
      "name": "noetl-ui",
      "version": "1.0.0"
    },
    "capabilities": {
      "transports": ["sse", "websocket"]
    }
  }
}
```

**Server → Client (Initialization response):**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {
      "name": "noetl-gateway",
      "version": "2.5.11"
    },
    "clientId": "uuid-client-id",
    "capabilities": {
      "playbooks": true,
      "callbacks": true
    }
  }
}
```

### Playbook Execution Request

**Client → Server (HTTP POST /graphql):**
```json
{
  "jsonrpc": "2.0",
  "id": "req-123",
  "method": "playbook/execute",
  "params": {
    "name": "api_integration/amadeus_ai_api",
    "variables": {
      "query": "Find flights from SFO to JFK"
    }
  }
}
```

**Server → Client (Immediate HTTP response):**
```json
{
  "jsonrpc": "2.0",
  "id": "req-123",
  "result": {
    "requestId": "uuid-request-id",
    "executionId": "552387377805656917",
    "status": "PENDING"
  }
}
```

### Callback Notification (Async via SSE/WS)

**Server → Client (Playbook result):**
```json
{
  "jsonrpc": "2.0",
  "method": "playbook/result",
  "params": {
    "requestId": "uuid-request-id",
    "executionId": "552387377805656917",
    "status": "COMPLETED",
    "data": {
      "textOutput": "## Flight Results\n\n**Flight 1**: UA 123...",
      "structuredData": { ... }
    }
  }
}
```

**Server → Client (Playbook error):**
```json
{
  "jsonrpc": "2.0",
  "method": "playbook/result",
  "params": {
    "requestId": "uuid-request-id",
    "executionId": "552387377805656917",
    "status": "FAILED",
    "error": {
      "code": -32000,
      "message": "Playbook execution failed",
      "data": {
        "step": "fetch_flights",
        "details": "API timeout"
      }
    }
  }
}
```

### Progress Updates (Optional)

**Server → Client (Progress notification):**
```json
{
  "jsonrpc": "2.0",
  "method": "playbook/progress",
  "params": {
    "requestId": "uuid-request-id",
    "executionId": "552387377805656917",
    "step": "process_results",
    "message": "Processing flight data...",
    "progress": 0.75
  }
}
```

### Heartbeat/Ping

**Server → Client:**
```json
{
  "jsonrpc": "2.0",
  "method": "ping"
}
```

**Client → Server (WebSocket only):**
```json
{
  "jsonrpc": "2.0",
  "method": "pong"
}
```

---

## Components

### 1. ConnectionHub (`src/connection_hub.rs`)

Manages active client connections across both SSE and WebSocket transports.

```rust
pub struct ConnectionHub {
    /// SSE connections: client_id -> sender
    sse_connections: Arc<RwLock<HashMap<String, SseSender>>>,
    /// WebSocket connections: client_id -> sender
    ws_connections: Arc<RwLock<HashMap<String, WsSender>>>,
    /// Session to clients mapping (one session can have multiple clients/tabs)
    session_clients: Arc<RwLock<HashMap<String, HashSet<String>>>>,
}

impl ConnectionHub {
    /// Register a new SSE connection
    pub fn register_sse(&self, client_id: String, session_token: String, sender: SseSender);

    /// Register a new WebSocket connection
    pub fn register_ws(&self, client_id: String, session_token: String, sender: WsSender);

    /// Unregister a connection (on disconnect)
    pub fn unregister(&self, client_id: &str);

    /// Send message to specific client
    pub async fn send_to_client(&self, client_id: &str, message: JsonRpcMessage) -> Result<()>;

    /// Send message to all clients of a session
    pub async fn send_to_session(&self, session_token: &str, message: JsonRpcMessage) -> Result<()>;

    /// Check if client is connected
    pub fn is_connected(&self, client_id: &str) -> bool;

    /// Get all client_ids for a session
    pub fn get_session_clients(&self, session_token: &str) -> Vec<String>;
}
```

### 2. RequestStore (`src/request_store.rs`)

NATS K/V backed store for tracking pending requests.

```rust
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct PendingRequest {
    pub client_id: String,
    pub session_token: String,
    pub execution_id: String,
    pub playbook_path: String,
    pub created_at: i64,
}

pub struct RequestStore {
    store: Arc<RwLock<Option<Store>>>,
    bucket_name: String,
    ttl_secs: u64,
}

impl RequestStore {
    /// Store a pending request
    pub async fn put(&self, request_id: &str, request: &PendingRequest) -> Result<()>;

    /// Get a pending request
    pub async fn get(&self, request_id: &str) -> Option<PendingRequest>;

    /// Remove a completed/failed request
    pub async fn remove(&self, request_id: &str) -> Result<()>;

    /// Get all pending requests for a client (for reconnection)
    pub async fn get_by_client(&self, client_id: &str) -> Vec<(String, PendingRequest)>;
}
```

### 3. SSE Endpoint (`GET /events`)

```rust
/// SSE event stream endpoint
///
/// Query params:
/// - session_token: Required for authentication
/// - client_id: Optional for reconnection (reuse existing client_id)
///
/// Returns: Server-Sent Events stream with JSON-RPC 2.0 messages
pub async fn sse_handler(
    State(state): State<Arc<AppState>>,
    Query(params): Query<SseParams>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>>;
```

### 4. WebSocket Endpoint (`GET /ws`) - Phase 2

```rust
/// WebSocket upgrade endpoint
///
/// Query params:
/// - session_token: Required for authentication
/// - client_id: Optional for reconnection
///
/// Returns: WebSocket connection for bidirectional JSON-RPC 2.0 messages
pub async fn ws_handler(
    State(state): State<Arc<AppState>>,
    Query(params): Query<WsParams>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse;
```

### 5. Callback Router (Updated `/api/internal/callback`)

```rust
/// Internal callback endpoint for workers
///
/// Receives playbook results and routes to connected clients
pub async fn callback_handler(
    State(state): State<Arc<AppState>>,
    Json(callback): Json<WorkerCallback>,
) -> impl IntoResponse {
    // 1. Look up request in RequestStore
    // 2. Find client_id from request
    // 3. Route message via ConnectionHub
    // 4. Remove request from store
}
```

---

## Configuration

### Environment Variables

```bash
# Existing NATS config
NATS_URL=nats://noetl:noetl@nats.nats.svc.cluster.local:4222

# Request store (new bucket)
NATS_REQUEST_BUCKET=requests
NATS_REQUEST_TTL_SECS=1800  # 30 minutes for long-running playbooks

# Transport config
GATEWAY_TRANSPORT_SSE_ENABLED=true
GATEWAY_TRANSPORT_WS_ENABLED=true  # Phase 2
GATEWAY_HEARTBEAT_INTERVAL_SECS=30
GATEWAY_CONNECTION_TIMEOUT_SECS=300  # 5 min idle timeout
```

### Config Struct

```rust
#[derive(Debug, Clone, Deserialize)]
pub struct TransportConfig {
    pub sse_enabled: bool,
    pub ws_enabled: bool,
    pub heartbeat_interval_secs: u64,
    pub connection_timeout_secs: u64,
    pub request_bucket: String,
    pub request_ttl_secs: u64,
}
```

---

## Request Flow

### 1. Client Connects (SSE)

```
Client                          Gateway                         NATS K/V
   │                               │                               │
   │ GET /events?session_token=xxx │                               │
   │──────────────────────────────>│                               │
   │                               │ Validate session              │
   │                               │ (check session cache)         │
   │                               │                               │
   │                               │ Generate client_id            │
   │                               │ Register in ConnectionHub     │
   │                               │                               │
   │      SSE: event: init         │                               │
   │      data: {clientId: "..."}  │                               │
   │<──────────────────────────────│                               │
   │                               │                               │
   │      SSE: event: ping         │                               │
   │      (every 30s)              │                               │
   │<──────────────────────────────│                               │
```

### 2. Execute Playbook (Async)

```
Client                          Gateway                         NoETL          Worker
   │                               │                               │               │
   │ POST /graphql                 │                               │               │
   │ {executePlaybook(...)}        │                               │               │
   │──────────────────────────────>│                               │               │
   │                               │                               │               │
   │                               │ Generate request_id           │               │
   │                               │                               │               │
   │                               │ Store pending request ─────────────────────────────>│
   │                               │                               │               │ NATS K/V
   │                               │                               │               │
   │                               │ POST /api/run/playbook        │               │
   │                               │ (with request_id, gateway_url)│               │
   │                               │──────────────────────────────>│               │
   │                               │                               │               │
   │                               │       {execution_id}          │               │
   │                               │<──────────────────────────────│               │
   │                               │                               │               │
   │ {requestId, executionId,      │                               │               │
   │  status: "PENDING"}           │                               │               │
   │<──────────────────────────────│                               │               │
   │                               │                               │               │
   │                               │                               │ dispatch      │
   │                               │                               │──────────────>│
   │                               │                               │               │
   │                               │                               │   execute     │
   │                               │                               │   playbook    │
   │                               │                               │               │
   │                               │     POST /api/internal/callback               │
   │                               │<──────────────────────────────────────────────│
   │                               │                               │               │
   │                               │ Lookup request_id             │               │
   │                               │ Find client_id                │               │
   │                               │                               │               │
   │      SSE: event: result       │                               │               │
   │      data: {requestId, ...}   │                               │               │
   │<──────────────────────────────│                               │               │
   │                               │                               │               │
   │                               │ Remove from RequestStore      │               │
   │                               │                               │               │
```

### 3. Reconnection Flow

```
Client                          Gateway                         NATS K/V
   │                               │                               │
   │ Connection lost...            │                               │
   │                               │                               │
   │ GET /events?session_token=xxx │                               │
   │           &client_id=old-id   │                               │
   │──────────────────────────────>│                               │
   │                               │ Validate session              │
   │                               │ Re-register with same         │
   │                               │ client_id if valid            │
   │                               │                               │
   │                               │ Get pending requests          │
   │                               │ for this client_id            │
   │                               │<──────────────────────────────│
   │                               │                               │
   │      SSE: event: init         │                               │
   │      data: {clientId,         │                               │
   │             pendingRequests}  │                               │
   │<──────────────────────────────│                               │
   │                               │                               │
   │ (Client knows which requests  │                               │
   │  are still pending)           │                               │
```

---

## Playbook Updates

Playbooks need to send callbacks to the gateway. The `gateway_url` and `request_id` are passed as args:

```yaml
workload:
  request_id: "{{ request_id }}"
  gateway_url: "{{ gateway_url | default('http://gateway.gateway.svc.cluster.local:8090') }}"

workflow:
  # ... playbook steps ...

  - step: send_result
    desc: Send result to gateway
    tool:
      kind: http
      method: POST
      url: "{{ workload.gateway_url }}/api/internal/callback"
      headers:
        Content-Type: application/json
      data:
        request_id: "{{ workload.request_id }}"
        execution_id: "{{ execution_id }}"
        status: "COMPLETED"
        data:
          textOutput: "{{ result.output }}"
```

---

## Error Codes (JSON-RPC 2.0 Standard)

| Code | Message | Description |
|------|---------|-------------|
| -32700 | Parse error | Invalid JSON |
| -32600 | Invalid request | Missing required fields |
| -32601 | Method not found | Unknown method |
| -32602 | Invalid params | Invalid method parameters |
| -32603 | Internal error | Internal server error |
| -32000 | Playbook failed | Playbook execution failed |
| -32001 | Timeout | Request timed out |
| -32002 | Unauthorized | Session invalid or expired |
| -32003 | Permission denied | No permission for playbook |

---

## UI Client Implementation

### SSE Connection (JavaScript)

```javascript
class NoetlClient {
  constructor(sessionToken) {
    this.sessionToken = sessionToken;
    this.clientId = localStorage.getItem('noetl_client_id');
    this.pendingRequests = new Map();
    this.eventSource = null;
  }

  connect() {
    const url = new URL('/events', window.location.origin);
    url.searchParams.set('session_token', this.sessionToken);
    if (this.clientId) {
      url.searchParams.set('client_id', this.clientId);
    }

    this.eventSource = new EventSource(url);

    this.eventSource.addEventListener('init', (e) => {
      const data = JSON.parse(e.data);
      this.clientId = data.result.clientId;
      localStorage.setItem('noetl_client_id', this.clientId);

      // Handle pending requests on reconnect
      if (data.result.pendingRequests) {
        // Update UI for pending requests
      }
    });

    this.eventSource.addEventListener('message', (e) => {
      const message = JSON.parse(e.data);
      this.handleMessage(message);
    });

    this.eventSource.addEventListener('error', (e) => {
      console.error('SSE error, reconnecting...');
      setTimeout(() => this.connect(), 3000);
    });
  }

  handleMessage(message) {
    if (message.method === 'playbook/result') {
      const { requestId, status, data, error } = message.params;
      const callback = this.pendingRequests.get(requestId);
      if (callback) {
        this.pendingRequests.delete(requestId);
        if (status === 'COMPLETED') {
          callback.resolve(data);
        } else {
          callback.reject(error);
        }
      }
    } else if (message.method === 'playbook/progress') {
      // Update progress UI
    }
  }

  async executePlaybook(name, variables) {
    const response = await fetch('/graphql', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.sessionToken}`
      },
      body: JSON.stringify({
        query: `mutation($name: String!, $vars: JSON) {
          executePlaybook(name: $name, variables: $vars) {
            requestId
            executionId
            status
          }
        }`,
        variables: { name, vars: variables }
      })
    });

    const result = await response.json();
    const { requestId, executionId } = result.data.executePlaybook;

    // Return promise that resolves when callback arrives
    return new Promise((resolve, reject) => {
      this.pendingRequests.set(requestId, { resolve, reject, executionId });
    });
  }
}
```

---

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
- [MCP JSON-RPC Reference Guide](https://portkey.ai/blog/mcp-message-types-complete-json-rpc-reference-guide/)
- [Server-Sent Events (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
