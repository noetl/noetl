// Configuration
const PLAYBOOK_NAME = 'api_integration/amadeus_ai_api';

// DOM Elements
const chatContainer = document.getElementById('chatContainer');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const sendButton = document.getElementById('sendButton');

// State
let isProcessing = false;
let sseReady = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  chatForm.addEventListener('submit', handleSubmit);
  chatInput.addEventListener('input', handleInputChange);

  // Listen for SSE connection
  window.addEventListener('sse-connected', (event) => {
    console.log('[app.js] SSE connected with clientId:', event.detail.clientId.substring(0, 8) + '...');
    sseReady = true;
    updateConnectionStatus(true);
  });

  // Listen for playbook progress updates
  window.addEventListener('playbook-progress', (event) => {
    const { message, step, progress } = event.detail;
    console.log('[app.js] Progress:', message || step, progress);
    // Could update typing indicator with progress message
  });
});

// Update connection status indicator (optional UI enhancement)
function updateConnectionStatus(connected) {
  const statusEl = document.getElementById('connectionStatus');
  if (statusEl) {
    statusEl.className = connected ? 'status-connected' : 'status-disconnected';
    statusEl.title = connected ? 'Real-time updates enabled' : 'Connecting...';
  }
}

// Handle form submission
async function handleSubmit(e) {
  e.preventDefault();

  const query = chatInput.value.trim();
  if (!query || isProcessing) return;

  // Check SSE connection
  if (!isSSEConnected()) {
    addErrorMessage('Real-time connection not established. Please wait or refresh the page.');
    return;
  }

  // Check playbook access before execution
  const hasAccess = await checkPlaybookAccess(PLAYBOOK_NAME, 'execute');
  if (!hasAccess) {
    addErrorMessage('You do not have permission to execute this playbook. Please contact your administrator.');
    return;
  }

  // Clear input
  chatInput.value = '';

  // Hide welcome message if it exists
  const welcomeMessage = chatContainer.querySelector('.welcome-message');
  if (welcomeMessage) {
    welcomeMessage.remove();
  }

  // Add user message
  addMessage(query, 'user');

  // Show typing indicator
  const typingIndicator = addTypingIndicator();

  // Disable input
  setProcessing(true);

  try {
    // Execute playbook with async callback via SSE
    const result = await executePlaybookAsync(PLAYBOOK_NAME, { query: query });

    // Remove typing indicator
    typingIndicator.remove();

    // Add assistant response
    if (result.textOutput) {
      addMessage(result.textOutput, 'assistant', result);
    } else {
      addMessage('I received your request but got no response. Please try again.', 'assistant', result);
    }
  } catch (error) {
    console.error('Error executing playbook:', error);
    typingIndicator.remove();

    if (error.message === 'Session expired' || error.message === 'Not authenticated') {
      addErrorMessage('Your session has expired. Redirecting to login...');
      setTimeout(() => {
        redirectToLogin();
      }, 2000);
    } else if (error.message.includes('timed out')) {
      addErrorMessage('The request took too long. Please try again.');
    } else {
      addErrorMessage(error.message || 'Failed to process your request. Please try again.');
    }
  } finally {
    setProcessing(false);
  }
}

// Legacy executePlaybook function (kept for fallback if SSE not available)
async function executePlaybookFallback(query) {
  const mutation = `
        mutation ExecuteAmadeus($name: String!, $vars: JSON) {
            executePlaybook(name: $name, variables: $vars) {
                id
                name
                status
                textOutput
            }
        }
    `;

  const variables = {
    name: PLAYBOOK_NAME,
    vars: {
      query: query
    }
  };

  // Use authenticated GraphQL function from auth.js
  const data = await authenticatedGraphQL(mutation, variables);
  return data.executePlaybook;
}

// Add message to chat
function addMessage(text, role, executionData = null) {
  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${role}`;

  const contentDiv = document.createElement('div');
  contentDiv.className = 'message-content';

  const textDiv = document.createElement('div');
  textDiv.className = 'message-text';

  // Format the text (convert markdown-like syntax to HTML)
  textDiv.innerHTML = formatMessage(text);

  contentDiv.appendChild(textDiv);

  // Add timestamp
  const timeDiv = document.createElement('div');
  timeDiv.className = 'message-time';
  timeDiv.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  contentDiv.appendChild(timeDiv);

  // Add execution info for assistant messages
  if (role === 'assistant' && executionData) {
    const infoDiv = document.createElement('div');
    infoDiv.className = 'execution-info';

    const statusBadge = document.createElement('span');
    statusBadge.className = `status-badge ${executionData.status.toLowerCase()}`;
    statusBadge.textContent = executionData.status;

    infoDiv.innerHTML = `Execution ID: ${executionData.id}`;
    infoDiv.appendChild(statusBadge);
    contentDiv.appendChild(infoDiv);
  }

  messageDiv.appendChild(contentDiv);
  chatContainer.appendChild(messageDiv);

  // Scroll to bottom
  scrollToBottom();
}

// Format message text (simple markdown-like formatting)
function formatMessage(text) {
  if (!text) return '';

  // Escape HTML
  text = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Convert markdown headers
  text = text.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  text = text.replace(/^## (.*$)/gim, '<h3>$1</h3>');

  // Convert bold
  text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

  // Convert line breaks
  text = text.replace(/\n\n/g, '</p><p>');
  text = text.replace(/\n/g, '<br>');

  // Wrap in paragraph if not already wrapped
  if (!text.startsWith('<h3>') && !text.startsWith('<p>')) {
    text = '<p>' + text + '</p>';
  }

  return text;
}

// Add typing indicator
function addTypingIndicator() {
  const messageDiv = document.createElement('div');
  messageDiv.className = 'message assistant typing';

  const indicatorDiv = document.createElement('div');
  indicatorDiv.className = 'typing-indicator';

  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('div');
    dot.className = 'typing-dot';
    indicatorDiv.appendChild(dot);
  }

  messageDiv.appendChild(indicatorDiv);
  chatContainer.appendChild(messageDiv);

  scrollToBottom();

  return messageDiv;
}

// Add error message
function addErrorMessage(message) {
  const errorDiv = document.createElement('div');
  errorDiv.className = 'error-message';
  errorDiv.innerHTML = `
        <span class="error-icon">⚠️</span>
        <span>${message}</span>
    `;
  chatContainer.appendChild(errorDiv);
  scrollToBottom();
}

// Handle input change
function handleInputChange() {
  const hasValue = chatInput.value.trim().length > 0;
  sendButton.disabled = !hasValue || isProcessing;
}

// Set processing state
function setProcessing(processing) {
  isProcessing = processing;
  chatInput.disabled = processing;
  sendButton.disabled = processing;

  if (processing) {
    chatInput.placeholder = 'Processing...';
  } else {
    chatInput.placeholder = "Ask about flights, e.g., 'I want to fly from SFO to JFK tomorrow'";
    chatInput.focus();
  }
}

// Scroll to bottom of chat
function scrollToBottom() {
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Send suggestion
function sendSuggestion(text) {
  chatInput.value = text;
  handleInputChange();
  chatForm.dispatchEvent(new Event('submit'));
}

// Make sendSuggestion available globally for onclick handlers
window.sendSuggestion = sendSuggestion;
