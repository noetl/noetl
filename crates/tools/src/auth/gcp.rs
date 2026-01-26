//! GCP Application Default Credentials authentication.

use std::sync::Arc;
use tokio::sync::RwLock;

use crate::error::ToolError;

/// Default GCP scopes for cloud platform access.
pub const DEFAULT_SCOPES: &[&str] = &["https://www.googleapis.com/auth/cloud-platform"];

/// GCP authentication provider using Application Default Credentials.
///
/// Uses gcp_auth's TokenProvider which handles:
/// 1. GOOGLE_APPLICATION_CREDENTIALS environment variable
/// 2. gcloud CLI configuration
/// 3. GCE/GKE metadata service
pub struct GcpAuth {
    /// Cached token provider (gcp_auth::provider() returns Arc<dyn TokenProvider>).
    provider: Arc<RwLock<Option<Arc<dyn gcp_auth::TokenProvider>>>>,
}

impl GcpAuth {
    /// Create a new GCP auth provider.
    pub fn new() -> Self {
        Self {
            provider: Arc::new(RwLock::new(None)),
        }
    }

    /// Initialize the provider lazily.
    async fn ensure_provider(&self) -> Result<(), ToolError> {
        // Check if already initialized
        {
            let guard = self.provider.read().await;
            if guard.is_some() {
                return Ok(());
            }
        }

        // Initialize using default provider chain
        let provider = gcp_auth::provider()
            .await
            .map_err(|e| ToolError::Auth(format!("Failed to initialize GCP auth: {}", e)))?;

        // Store for future use
        {
            let mut guard = self.provider.write().await;
            *guard = Some(provider);
        }

        Ok(())
    }

    /// Get an access token for the given scopes.
    ///
    /// Uses Application Default Credentials (ADC) which checks:
    /// 1. GOOGLE_APPLICATION_CREDENTIALS environment variable
    /// 2. gcloud CLI configuration
    /// 3. GCE/GKE metadata service
    pub async fn get_token(&self, scopes: &[&str]) -> Result<String, ToolError> {
        self.ensure_provider().await?;

        let guard = self.provider.read().await;
        let provider = guard
            .as_ref()
            .ok_or_else(|| ToolError::Auth("GCP provider not initialized".to_string()))?;

        let token = provider
            .token(scopes)
            .await
            .map_err(|e| ToolError::Auth(format!("Failed to get GCP token: {}", e)))?;

        Ok(token.as_str().to_string())
    }

    /// Get an access token with default cloud platform scope.
    pub async fn get_default_token(&self) -> Result<String, ToolError> {
        self.get_token(DEFAULT_SCOPES).await
    }
}

impl Default for GcpAuth {
    fn default() -> Self {
        Self::new()
    }
}

impl Clone for GcpAuth {
    fn clone(&self) -> Self {
        Self {
            provider: Arc::clone(&self.provider),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_scopes() {
        assert!(DEFAULT_SCOPES.contains(&"https://www.googleapis.com/auth/cloud-platform"));
    }

    #[test]
    fn test_gcp_auth_new() {
        let auth = GcpAuth::new();
        // Just verify it can be created
        let _ = auth;
    }

    #[test]
    fn test_gcp_auth_clone() {
        let auth = GcpAuth::new();
        let cloned = auth.clone();
        // Both should share the same provider
        assert!(Arc::ptr_eq(&auth.provider, &cloned.provider));
    }
}
