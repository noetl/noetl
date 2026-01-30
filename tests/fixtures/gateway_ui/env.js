// Environment Configuration for Gateway UI
//
// This file provides environment-specific configuration.
// Modify this file to point to different gateway endpoints.
//
// Environments:
//   - local:  Direct localhost (cargo run)
//   - kind:   Kind Kubernetes cluster with NodePort
//   - gke:    Google Kubernetes Engine (production)

(function() {
  // Environment detection based on hostname
  const hostname = window.location.hostname;
  const port = window.location.port;

  // Determine environment
  // Default to 'kind' for localhost since that's the typical dev setup
  // (UI on 8080, gateway on 8090 via Kind port mapping)
  let detectedEnv = 'kind';

  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    // Port 8080 = UI server, gateway is on 8090 -> use 'kind'
    // Port 8090 = gateway directly (rare, testing only) -> use 'local'
    // Port 30000+ = inside cluster -> use 'kind'
    if (port === '8090') {
      detectedEnv = 'local';
    } else {
      detectedEnv = 'kind';
    }
  } else if (hostname.includes('mestumre.dev') || hostname.includes('noetl.io')) {
    detectedEnv = 'gke';
  }

  // Allow manual override via URL parameter: ?env=kind
  const urlParams = new URLSearchParams(window.location.search);
  const envOverride = urlParams.get('env');
  if (envOverride && ['local', 'kind', 'gke'].includes(envOverride)) {
    detectedEnv = envOverride;
  }

  // Environment-specific configurations
  // Port mappings from ci/kind/config.yaml:
  //   - Gateway API: containerPort 30090 -> hostPort 8090
  //   - Gateway UI: containerPort 30080 -> hostPort 8080
  const configs = {
    local: {
      name: 'Local Development',
      gatewayUrl: 'http://localhost:8080',
      description: 'Direct connection to locally running gateway (cargo run)'
    },
    kind: {
      name: 'Kind Kubernetes Cluster',
      gatewayUrl: 'http://localhost:8090',
      description: 'Connection via Kind port mapping (hostPort 8090 -> containerPort 30090)'
    },
    gke: {
      name: 'GKE Production',
      gatewayUrl: 'https://gateway.mestumre.dev',
      description: 'Production Google Kubernetes Engine deployment'
    }
  };

  // Export configuration globally
  const config = configs[detectedEnv];

  window.ENV = {
    current: detectedEnv,
    name: config.name,
    gatewayUrl: config.gatewayUrl,
    description: config.description,

    // Helper to get full API URL
    apiUrl: function(path) {
      return this.gatewayUrl + (path.startsWith('/') ? path : '/' + path);
    },

    // Log current environment
    log: function() {
      console.log(`[ENV] ${this.name} (${this.current})`);
      console.log(`[ENV] Gateway: ${this.gatewayUrl}`);
    }
  };

  // Auto-log on load
  window.ENV.log();
})();
