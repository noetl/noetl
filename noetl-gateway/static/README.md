# Amadeus AI Chat Interface

Beautiful chat interface for the Amadeus AI flight search assistant.

## Files

- `index.html` - Main HTML structure
- `styles.css` - Beautiful gradient design with animations
- `app.js` - GraphQL integration and chat functionality

## Features

- 🎨 Beautiful gradient design (purple/blue theme)
- 💬 Real-time chat interface with typing indicators
- ✈️ Pre-built suggestion chips for quick queries
- 📱 Fully responsive (mobile and desktop)
- 🎭 Smooth animations and transitions
- ⚡ GraphQL integration with error handling
- 📊 Execution status badges

## Configuration

Update the GraphQL endpoint in `app.js`:

```javascript
const GRAPHQL_ENDPOINT = '/graphql'; // Change to your actual endpoint
```

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
