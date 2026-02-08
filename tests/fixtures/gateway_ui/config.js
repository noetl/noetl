// Auth0 Configuration
// Update this file to change Auth0 settings
const isLocalDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const auth0Config = {
  domain: 'mestumre-development.us.auth0.com',
  clientId: 'Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN',
  // Redirect back to login.html
  // Port mapping (from ci/kind/config.yaml):
  //   - 8080: UI server (Python HTTP server for development)
  //   - 8090: Gateway API (Kind hostPort -> containerPort 30090)
  // NOTE: Auth0 callback URLs must be configured to allow this port
  redirectUri: isLocalDev ? 'http://localhost:8080/login.html' : window.location.origin + '/login.html'
};
