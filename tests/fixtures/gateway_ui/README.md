# Gateway UI Test Fixtures

Static UI files for testing the NoETL Gateway authentication and GraphQL integration.

## Files

- `index.html` - Main application page (flight search demo)
- `login.html` - Authentication login page
- `app.js` - Main application logic with GraphQL integration
- `auth.js` - Authentication utilities (session management, token validation)
- `styles.css` - Shared styles for UI

## Features

- 🔐 Auth0 authentication integration
- 🎨 Beautiful gradient design (purple/blue theme)
- 💬 Real-time chat interface with typing indicators
- ✈️ Flight search with Amadeus AI API
- 📱 Fully responsive (mobile and desktop)
- 🎭 Smooth animations and transitions
- ⚡ GraphQL integration with error handling
- 🔒 Session-based access control

## How It Works

These are **pure static files** (HTML/JS/CSS) that connect to the Gateway API via JavaScript fetch calls.

The JavaScript files make HTTP requests to:
- `http://localhost:8090/api/auth/*` - Authentication endpoints
- `http://localhost:8090/graphql` - GraphQL endpoint

**You can serve these files any way you want:**

### Local Development Options

**Option 1: Python (Quick & Easy)**
```bash
cd tests/fixtures/gateway_ui
python3 -m http.server 8080
```

**Option 2: Node.js**
```bash
npx http-server -p 8080 --cors
```

The UI connects to the Gateway API. Update these URLs if needed:

**For local development with different ports:**

In `auth.js`:
```javascript
// Change this if gateway is on different port/host
const API_BASE = 'http://localhost:8090'; // Gateway API URL
```

In `app.js`:
```javascript
// Uses authenticatedGraphQL from auth.js which calls ${API_BASE}/graphql
```

**For production:**
```javascript
const API_BASE = 'https://api.yourdomain.com'; // Your production gateway
```

The HTML/JS files are **completely separate** from the gateway - they're just a frontend that makes API calls.n tests/fixtures/gateway_ui/login.html
# or double-click login.html in Finder
```
⚠️ Note: Opening as `file://` may cause CORS issues. Use HTTP server for full functionality.

### Production Deployment

In production, serve these files with:
- **Nginx** - Standard web server
- **Apache** - Traditional web server  
- **CDN** - CloudFront, Cloudflare, Fastly
- **Object Storage** - S3 + CloudFront, GCS, Azure Blob
- **Vercel/Netlify** - Serverless static hosting

Then update `API_BASE` in `auth.js` to point to your gateway URL.

## Configuration

Update the API base URL if your gateway runs on a different port:

In `auth.js`:
```javascript
const API_BASE = window.location.origin; // Or 'http://localhost:8090'
```

## Gateway Integration

The UI communicates with these Gateway endpoints:

- `POST /api/auth/login` - Auth0 login
- `POST /api/auth/validate` - Session validation
- `POST /api/auth/check-access` - Permission checking
- `POST /graphql` - Protected GraphQL endpoint (requires authentication)

## Testing Flow

1. **Start Gateway**: `cd gateway && cargo run --release`
2. **Start UI server**: `cd tests/fixtures/gateway_ui && python3 -m http.server 8080`
3. **Open browser**: `http://localhost:8080/login.html`
4. **Login**: Use Auth0 token or test session token
5. **Test flight search**: Query flights on main page

## Creating Test Session

```sql
-- Connect to PostgreSQL
psql -h localhost -p 54321 -U demo -d demo_noetl

-- Create test user and session
INSERT INTO auth.users (auth0_id, email, display_name, is_active)
VALUES ('auth0|test123', 'test@example.com', 'Test User', true)
RETURNING user_id;

-- Grant admin role (use user_id from above)
INSERT INTO auth.user_roles (user_id, role_id)
SELECT 1, role_id FROM auth.roles WHERE role_name = 'admin';

-- Create test session (expires in 8 hours)
INSERT INTO auth.sessions (user_id, session_token, expires_at)
VALUES (1, 'test-session-token-12345', NOW() + INTERVAL '8 hours')
RETURNING session_token;
```

Use the returned `session_token` for direct login testing.

## GraphQL Integration

The interface uses this mutation:

```graphql
mutation ExecuteAmadeus($name: String!, $vars: JSON) {
  executePlaybook(name: $name, variables: $vars) {
    id
    name
    status
    textOutput
  }
}
```

With variables:
```json
{
  "name": "api_integration/amadeus_ai_api",
  "vars": {
    "query": "User's flight search query"
  }
}
```

## Usage

### Option 1: Serve with your Rust application

Add to your `main.rs`:

```rust
use axum::{
    Router,
    routing::get_service,
};
use tower_http::services::ServeDir;

let app = Router::new()
    .nest_service("/", ServeDir::new("static"));
```

### Option 2: Simple HTTP server

```bash
# Using Python
cd static
python3 -m http.server 8000

# Or using Node.js
npx http-server static -p 8000
```

Then open: http://localhost:8000

## Customization

### Colors

Edit CSS variables in `styles.css`:

```css
:root {
    --primary-color: #667eea;
    --secondary-color: #764ba2;
    /* ... more colors */
}
```

### Suggestions

Edit suggestion chips in `index.html`:

```html
<button class="suggestion-chip" onclick="sendSuggestion('Your custom query')">
    Your button text
</button>
```

### GraphQL Endpoint

The default endpoint is `/graphql`. Update in `app.js` if different:

```javascript
const GRAPHQL_ENDPOINT = 'http://your-server:port/graphql';
```

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Features Breakdown

### User Interface
- Gradient header with avatar icon
- Chat bubbles with timestamps
- Typing indicator animation
- Error messages with icons
- Execution status badges

### Functionality
- Send text queries
- Quick suggestion buttons
- Real-time GraphQL queries
- Response formatting (markdown-like)
- Auto-scroll to latest message
- Input validation
- Loading states

## Example Queries

Try these in the chat:
- "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult"
- "Show me flights from LAX to Miami next week for 2 passengers"
- "I need a round trip from New York to London in April"
- "Find flights from Chicago to Paris on June 10th"

## Troubleshooting

### CORS Issues
If you get CORS errors, ensure your server allows requests from the origin serving the HTML:

```rust
// Add CORS middleware in your Rust application
use tower_http::cors::CorsLayer;

let app = Router::new()
    .layer(CorsLayer::permissive());
```

### GraphQL Errors
Check browser console for detailed error messages. The chat will display user-friendly error messages.

### Styling Issues
Clear browser cache if styles don't update after changes.
