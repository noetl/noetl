// Auth0 Configuration
// Update this file to change Auth0 settings
const isLocalDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const auth0Config = {
  domain: 'mestumre-development.us.auth0.com',
  clientId: 'Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN',
  // Redirect back to login.html - use port 8090 for local dev (Auth0 allowed callback)
  redirectUri: isLocalDev ? 'http://localhost:8090/login.html' : window.location.origin + '/login.html'
};
