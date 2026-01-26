//! Authentication resolver.
//!
//! Resolves authentication configuration to credentials.

use super::gcp::GcpAuth;
use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{AuthConfig, AuthType};

/// Resolved authentication credentials.
#[derive(Debug, Clone)]
pub enum AuthCredentials {
    /// Bearer token.
    Bearer(String),
    /// Basic auth (username, password).
    Basic(String, String),
    /// API key (header name, value).
    ApiKey(String, String),
    /// No authentication.
    None,
}

impl AuthCredentials {
    /// Apply credentials to a reqwest request builder.
    pub fn apply_to_request(
        &self,
        request: reqwest::RequestBuilder,
    ) -> reqwest::RequestBuilder {
        match self {
            AuthCredentials::Bearer(token) => request.bearer_auth(token),
            AuthCredentials::Basic(username, password) => request.basic_auth(username, Some(password)),
            AuthCredentials::ApiKey(header, value) => request.header(header.as_str(), value.as_str()),
            AuthCredentials::None => request,
        }
    }
}

/// Authentication resolver.
///
/// Resolves auth configuration to actual credentials.
pub struct AuthResolver {
    gcp_auth: GcpAuth,
}

impl AuthResolver {
    /// Create a new auth resolver.
    pub fn new() -> Self {
        Self {
            gcp_auth: GcpAuth::new(),
        }
    }

    /// Create a new auth resolver with a specific GCP auth provider.
    pub fn with_gcp_auth(gcp_auth: GcpAuth) -> Self {
        Self { gcp_auth }
    }

    /// Resolve authentication configuration to credentials.
    pub async fn resolve(
        &self,
        config: &AuthConfig,
        ctx: &ExecutionContext,
    ) -> Result<AuthCredentials, ToolError> {
        match config.auth_type {
            AuthType::Bearer => self.resolve_bearer(config, ctx).await,
            AuthType::Basic => self.resolve_basic(config, ctx),
            AuthType::ApiKey => self.resolve_api_key(config, ctx),
            AuthType::GcpAdc => self.resolve_gcp_adc(config).await,
            AuthType::None => Ok(AuthCredentials::None),
        }
    }

    /// Get GCP token directly.
    pub async fn get_gcp_token(&self, scopes: Option<&[&str]>) -> Result<String, ToolError> {
        match scopes {
            Some(scopes) => self.gcp_auth.get_token(scopes).await,
            None => self.gcp_auth.get_default_token().await,
        }
    }

    /// Resolve bearer token authentication.
    async fn resolve_bearer(
        &self,
        config: &AuthConfig,
        ctx: &ExecutionContext,
    ) -> Result<AuthCredentials, ToolError> {
        // Direct token takes precedence
        if let Some(ref token) = config.token {
            return Ok(AuthCredentials::Bearer(token.clone()));
        }

        // Try credential lookup
        if let Some(ref credential) = config.credential {
            if let Some(token) = ctx.get_secret(credential) {
                return Ok(AuthCredentials::Bearer(token.to_string()));
            }
            return Err(ToolError::Auth(format!(
                "Credential '{}' not found in context",
                credential
            )));
        }

        Err(ToolError::Auth(
            "Bearer auth requires 'token' or 'credential'".to_string(),
        ))
    }

    /// Resolve basic authentication.
    fn resolve_basic(
        &self,
        config: &AuthConfig,
        ctx: &ExecutionContext,
    ) -> Result<AuthCredentials, ToolError> {
        // Try credential lookup for password
        let password = if let Some(ref credential) = config.credential {
            ctx.get_secret(credential)
                .ok_or_else(|| {
                    ToolError::Auth(format!("Credential '{}' not found in context", credential))
                })?
                .to_string()
        } else {
            config
                .password
                .clone()
                .ok_or_else(|| ToolError::Auth("Basic auth requires 'password'".to_string()))?
        };

        let username = config
            .username
            .clone()
            .ok_or_else(|| ToolError::Auth("Basic auth requires 'username'".to_string()))?;

        Ok(AuthCredentials::Basic(username, password))
    }

    /// Resolve API key authentication.
    fn resolve_api_key(
        &self,
        config: &AuthConfig,
        ctx: &ExecutionContext,
    ) -> Result<AuthCredentials, ToolError> {
        let header = config
            .header
            .clone()
            .unwrap_or_else(|| "X-API-Key".to_string());

        // Try credential lookup
        let value = if let Some(ref credential) = config.credential {
            ctx.get_secret(credential)
                .ok_or_else(|| {
                    ToolError::Auth(format!("Credential '{}' not found in context", credential))
                })?
                .to_string()
        } else if let Some(ref token) = config.token {
            token.clone()
        } else {
            return Err(ToolError::Auth(
                "API key auth requires 'token' or 'credential'".to_string(),
            ));
        };

        Ok(AuthCredentials::ApiKey(header, value))
    }

    /// Resolve GCP ADC authentication.
    async fn resolve_gcp_adc(&self, config: &AuthConfig) -> Result<AuthCredentials, ToolError> {
        let scopes: Vec<&str> = config
            .scopes
            .as_ref()
            .map(|s| s.iter().map(|s| s.as_str()).collect())
            .unwrap_or_else(|| vec!["https://www.googleapis.com/auth/cloud-platform"]);

        let token = self.gcp_auth.get_token(&scopes).await?;
        Ok(AuthCredentials::Bearer(token))
    }
}

impl Default for AuthResolver {
    fn default() -> Self {
        Self::new()
    }
}

impl Clone for AuthResolver {
    fn clone(&self) -> Self {
        Self {
            gcp_auth: self.gcp_auth.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_auth_credentials_none() {
        let creds = AuthCredentials::None;
        assert!(matches!(creds, AuthCredentials::None));
    }

    #[test]
    fn test_auth_credentials_bearer() {
        let creds = AuthCredentials::Bearer("token123".to_string());
        assert!(matches!(creds, AuthCredentials::Bearer(_)));
    }

    #[test]
    fn test_auth_credentials_basic() {
        let creds = AuthCredentials::Basic("user".to_string(), "pass".to_string());
        assert!(matches!(creds, AuthCredentials::Basic(_, _)));
    }

    #[test]
    fn test_auth_credentials_api_key() {
        let creds = AuthCredentials::ApiKey("X-API-Key".to_string(), "key123".to_string());
        assert!(matches!(creds, AuthCredentials::ApiKey(_, _)));
    }

    #[tokio::test]
    async fn test_resolve_bearer_with_token() {
        let resolver = AuthResolver::new();
        let config = AuthConfig {
            auth_type: AuthType::Bearer,
            token: Some("direct-token".to_string()),
            credential: None,
            username: None,
            password: None,
            header: None,
            scopes: None,
        };
        let ctx = ExecutionContext::default();

        let result = resolver.resolve(&config, &ctx).await.unwrap();
        assert!(matches!(result, AuthCredentials::Bearer(t) if t == "direct-token"));
    }

    #[tokio::test]
    async fn test_resolve_bearer_with_credential() {
        let resolver = AuthResolver::new();
        let config = AuthConfig {
            auth_type: AuthType::Bearer,
            token: None,
            credential: Some("my-token".to_string()),
            username: None,
            password: None,
            header: None,
            scopes: None,
        };
        let mut ctx = ExecutionContext::default();
        ctx.set_secret("my-token", "secret-token");

        let result = resolver.resolve(&config, &ctx).await.unwrap();
        assert!(matches!(result, AuthCredentials::Bearer(t) if t == "secret-token"));
    }

    #[tokio::test]
    async fn test_resolve_bearer_missing_credential() {
        let resolver = AuthResolver::new();
        let config = AuthConfig {
            auth_type: AuthType::Bearer,
            token: None,
            credential: Some("missing".to_string()),
            username: None,
            password: None,
            header: None,
            scopes: None,
        };
        let ctx = ExecutionContext::default();

        let result = resolver.resolve(&config, &ctx).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_resolve_basic() {
        let resolver = AuthResolver::new();
        let config = AuthConfig {
            auth_type: AuthType::Basic,
            token: None,
            credential: None,
            username: Some("user".to_string()),
            password: Some("pass".to_string()),
            header: None,
            scopes: None,
        };
        let ctx = ExecutionContext::default();

        let result = resolver.resolve(&config, &ctx).await.unwrap();
        assert!(matches!(result, AuthCredentials::Basic(u, p) if u == "user" && p == "pass"));
    }

    #[tokio::test]
    async fn test_resolve_api_key() {
        let resolver = AuthResolver::new();
        let config = AuthConfig {
            auth_type: AuthType::ApiKey,
            token: Some("api-key-value".to_string()),
            credential: None,
            username: None,
            password: None,
            header: Some("X-Custom-Key".to_string()),
            scopes: None,
        };
        let ctx = ExecutionContext::default();

        let result = resolver.resolve(&config, &ctx).await.unwrap();
        assert!(
            matches!(result, AuthCredentials::ApiKey(h, v) if h == "X-Custom-Key" && v == "api-key-value")
        );
    }

    #[tokio::test]
    async fn test_resolve_none() {
        let resolver = AuthResolver::new();
        let config = AuthConfig {
            auth_type: AuthType::None,
            token: None,
            credential: None,
            username: None,
            password: None,
            header: None,
            scopes: None,
        };
        let ctx = ExecutionContext::default();

        let result = resolver.resolve(&config, &ctx).await.unwrap();
        assert!(matches!(result, AuthCredentials::None));
    }
}
