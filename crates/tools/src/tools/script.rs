//! Script execution tool using Kubernetes jobs.

use async_trait::async_trait;
use k8s_openapi::api::batch::v1::Job;
use k8s_openapi::api::core::v1::{ConfigMap, Container, EnvVar, Pod, PodSpec, Secret, Volume, VolumeMount};
use kube::api::{Api, DeleteParams, ListParams, PostParams};
use kube::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::context::ExecutionContext;
use crate::error::ToolError;
use crate::registry::{Tool, ToolConfig};
use crate::result::ToolResult;
use crate::template::TemplateEngine;

/// Script source type.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ScriptSourceType {
    /// Script from Google Cloud Storage.
    Gcs,
    /// Script from AWS S3.
    S3,
    /// Script from HTTP URL.
    Http,
    /// Local script (inline).
    Local,
    /// Inline script content.
    Inline,
}

/// Script source configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScriptSource {
    /// Source type.
    #[serde(rename = "type")]
    pub source_type: ScriptSourceType,

    /// URI for remote scripts.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub uri: Option<String>,

    /// Inline script content.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
}

/// Resource requirements.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ResourceRequirements {
    /// Resource requests.
    #[serde(default)]
    pub requests: HashMap<String, String>,

    /// Resource limits.
    #[serde(default)]
    pub limits: HashMap<String, String>,
}

/// Job configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobConfig {
    /// Container image to use.
    #[serde(default = "default_image")]
    pub image: String,

    /// Kubernetes namespace.
    #[serde(default = "default_namespace")]
    pub namespace: String,

    /// TTL seconds after job finishes.
    #[serde(default = "default_ttl")]
    pub ttl_seconds_after_finished: i32,

    /// Backoff limit for retries.
    #[serde(default = "default_backoff_limit")]
    pub backoff_limit: i32,

    /// Timeout in seconds.
    #[serde(default = "default_timeout")]
    pub timeout: i64,

    /// Dependencies to install.
    #[serde(default)]
    pub install_dependencies: Vec<String>,

    /// Resource requirements.
    #[serde(default)]
    pub resources: ResourceRequirements,

    /// Environment variables.
    #[serde(default)]
    pub env: HashMap<String, String>,

    /// Image pull policy.
    #[serde(default = "default_pull_policy")]
    pub image_pull_policy: String,
}

fn default_image() -> String {
    "python:3.11-slim".to_string()
}

fn default_namespace() -> String {
    "noetl".to_string()
}

fn default_ttl() -> i32 {
    300
}

fn default_backoff_limit() -> i32 {
    3
}

fn default_timeout() -> i64 {
    600
}

fn default_pull_policy() -> String {
    "IfNotPresent".to_string()
}

impl Default for JobConfig {
    fn default() -> Self {
        Self {
            image: default_image(),
            namespace: default_namespace(),
            ttl_seconds_after_finished: default_ttl(),
            backoff_limit: default_backoff_limit(),
            timeout: default_timeout(),
            install_dependencies: vec![],
            resources: ResourceRequirements::default(),
            env: HashMap::new(),
            image_pull_policy: default_pull_policy(),
        }
    }
}

/// Script tool configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScriptConfig {
    /// Script source configuration.
    pub script: ScriptSource,

    /// Job configuration.
    #[serde(default)]
    pub job: JobConfig,

    /// Arguments to pass to the script.
    #[serde(default)]
    pub args: HashMap<String, serde_json::Value>,
}

/// Script execution result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScriptResultData {
    /// Execution status.
    pub status: String,

    /// Job name.
    pub job_name: String,

    /// Namespace.
    pub namespace: String,

    /// Pod name (if available).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pod_name: Option<String>,

    /// Execution time in seconds.
    pub execution_time: f64,

    /// Job output (logs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output: Option<String>,

    /// Number of succeeded pods.
    pub succeeded: i32,

    /// Number of failed pods.
    pub failed: i32,

    /// Exit code (if available).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exit_code: Option<i32>,
}

/// Script execution tool using Kubernetes jobs.
pub struct ScriptTool {
    http_client: reqwest::Client,
    template_engine: TemplateEngine,
}

impl ScriptTool {
    /// Create a new script tool.
    pub fn new() -> Self {
        Self {
            http_client: reqwest::Client::new(),
            template_engine: TemplateEngine::new(),
        }
    }

    /// Execute a script as a Kubernetes job.
    pub async fn execute_script(
        &self,
        config: &ScriptConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let start = std::time::Instant::now();

        // Get Kubernetes client
        let client = Client::try_default()
            .await
            .map_err(|e| ToolError::Configuration(format!("Failed to create K8s client: {}", e)))?;

        // Load script content
        let script_content = self.load_script(&config.script).await?;

        // Generate unique job name
        let job_name = format!(
            "noetl-script-{}-{}",
            ctx.execution_id,
            uuid::Uuid::new_v4().to_string().split('-').next().unwrap_or("xxxx")
        );

        let namespace = &config.job.namespace;

        // Create ConfigMap for script
        let configmap_name = format!("{}-script", job_name);
        self.create_script_configmap(&client, namespace, &configmap_name, &script_content)
            .await?;

        // Create Secret for environment variables if needed
        let secret_name = if !config.job.env.is_empty() {
            let name = format!("{}-env", job_name);
            self.create_env_secret(&client, namespace, &name, &config.job.env)
                .await?;
            Some(name)
        } else {
            None
        };

        // Create and run the job
        let job = self
            .create_job(
                &client,
                namespace,
                &job_name,
                &configmap_name,
                secret_name.as_deref(),
                config,
            )
            .await?;

        // Wait for job completion
        let result = self
            .wait_for_job(&client, namespace, &job_name, config.job.timeout)
            .await?;

        // Get pod logs
        let pod_name = self.get_job_pod(&client, namespace, &job_name).await?;
        let output = if let Some(ref pn) = pod_name {
            self.get_pod_logs(&client, namespace, pn).await.ok()
        } else {
            None
        };

        let execution_time = start.elapsed().as_secs_f64();

        // Clean up ConfigMap and Secret (job has TTL)
        let _ = self
            .cleanup_resources(&client, namespace, &configmap_name, secret_name.as_deref())
            .await;

        let result_data = ScriptResultData {
            status: result.status,
            job_name,
            namespace: namespace.clone(),
            pod_name,
            execution_time,
            output,
            succeeded: result.succeeded,
            failed: result.failed,
            exit_code: result.exit_code,
        };

        let duration_ms = start.elapsed().as_millis() as u64;

        if result.succeeded > 0 && result.failed == 0 {
            Ok(ToolResult::success(serde_json::to_value(&result_data).unwrap())
                .with_duration(duration_ms))
        } else {
            Ok(ToolResult::error(format!("Job failed with {} failures", result.failed))
                .with_data(serde_json::to_value(&result_data).unwrap())
                .with_duration(duration_ms))
        }
    }

    /// Load script content from source.
    async fn load_script(&self, source: &ScriptSource) -> Result<String, ToolError> {
        match source.source_type {
            ScriptSourceType::Inline | ScriptSourceType::Local => {
                source.content.clone().ok_or_else(|| {
                    ToolError::Configuration("Script content required for inline/local source".to_string())
                })
            }
            ScriptSourceType::Http => {
                let uri = source.uri.as_ref().ok_or_else(|| {
                    ToolError::Configuration("URI required for HTTP script source".to_string())
                })?;

                self.http_client
                    .get(uri)
                    .send()
                    .await
                    .map_err(|e| ToolError::Http(format!("Failed to fetch script: {}", e)))?
                    .text()
                    .await
                    .map_err(|e| ToolError::Http(format!("Failed to read script: {}", e)))
            }
            ScriptSourceType::Gcs | ScriptSourceType::S3 => {
                // For GCS/S3, we would need the appropriate SDK
                // For now, return an error suggesting HTTP alternative
                Err(ToolError::Configuration(
                    "GCS/S3 script sources require authentication. Use HTTP with signed URLs instead.".to_string(),
                ))
            }
        }
    }

    /// Create a ConfigMap containing the script.
    async fn create_script_configmap(
        &self,
        client: &Client,
        namespace: &str,
        name: &str,
        content: &str,
    ) -> Result<(), ToolError> {
        let configmaps: Api<ConfigMap> = Api::namespaced(client.clone(), namespace);

        let cm = ConfigMap {
            metadata: kube::api::ObjectMeta {
                name: Some(name.to_string()),
                namespace: Some(namespace.to_string()),
                ..Default::default()
            },
            data: Some({
                let mut data = std::collections::BTreeMap::new();
                data.insert("script.py".to_string(), content.to_string());
                data
            }),
            ..Default::default()
        };

        configmaps
            .create(&PostParams::default(), &cm)
            .await
            .map_err(|e| ToolError::Configuration(format!("Failed to create ConfigMap: {}", e)))?;

        Ok(())
    }

    /// Create a Secret containing environment variables.
    async fn create_env_secret(
        &self,
        client: &Client,
        namespace: &str,
        name: &str,
        env: &HashMap<String, String>,
    ) -> Result<(), ToolError> {
        let secrets: Api<Secret> = Api::namespaced(client.clone(), namespace);

        let secret = Secret {
            metadata: kube::api::ObjectMeta {
                name: Some(name.to_string()),
                namespace: Some(namespace.to_string()),
                ..Default::default()
            },
            string_data: Some(env.clone().into_iter().collect()),
            ..Default::default()
        };

        secrets
            .create(&PostParams::default(), &secret)
            .await
            .map_err(|e| ToolError::Configuration(format!("Failed to create Secret: {}", e)))?;

        Ok(())
    }

    /// Create and submit the Kubernetes job.
    async fn create_job(
        &self,
        client: &Client,
        namespace: &str,
        job_name: &str,
        configmap_name: &str,
        secret_name: Option<&str>,
        config: &ScriptConfig,
    ) -> Result<Job, ToolError> {
        let jobs: Api<Job> = Api::namespaced(client.clone(), namespace);

        // Build container command
        let mut command_parts = vec![];

        // Install dependencies if specified
        if !config.job.install_dependencies.is_empty() {
            let deps = config.job.install_dependencies.join(" ");
            command_parts.push(format!("pip install {} && ", deps));
        }

        // Run the script with args
        let args_json = serde_json::to_string(&config.args).unwrap_or_else(|_| "{}".to_string());
        command_parts.push(format!(
            "python /scripts/script.py '{}'",
            args_json.replace('\'', "'\"'\"'")
        ));

        let command = command_parts.join("");

        // Build environment variables
        let mut env_vars = vec![];
        if let Some(sn) = secret_name {
            // Add all secret keys as env vars
            for key in config.job.env.keys() {
                env_vars.push(EnvVar {
                    name: key.clone(),
                    value_from: Some(k8s_openapi::api::core::v1::EnvVarSource {
                        secret_key_ref: Some(k8s_openapi::api::core::v1::SecretKeySelector {
                            name: sn.to_string(),
                            key: key.clone(),
                            optional: Some(false),
                        }),
                        ..Default::default()
                    }),
                    ..Default::default()
                });
            }
        }

        // Build resource requirements
        let resources = if config.job.resources.requests.is_empty()
            && config.job.resources.limits.is_empty()
        {
            None
        } else {
            Some(k8s_openapi::api::core::v1::ResourceRequirements {
                requests: if config.job.resources.requests.is_empty() {
                    None
                } else {
                    Some(
                        config
                            .job
                            .resources
                            .requests
                            .iter()
                            .map(|(k, v)| {
                                (
                                    k.clone(),
                                    k8s_openapi::apimachinery::pkg::api::resource::Quantity(
                                        v.clone(),
                                    ),
                                )
                            })
                            .collect(),
                    )
                },
                limits: if config.job.resources.limits.is_empty() {
                    None
                } else {
                    Some(
                        config
                            .job
                            .resources
                            .limits
                            .iter()
                            .map(|(k, v)| {
                                (
                                    k.clone(),
                                    k8s_openapi::apimachinery::pkg::api::resource::Quantity(
                                        v.clone(),
                                    ),
                                )
                            })
                            .collect(),
                    )
                },
                ..Default::default()
            })
        };

        let job = Job {
            metadata: kube::api::ObjectMeta {
                name: Some(job_name.to_string()),
                namespace: Some(namespace.to_string()),
                ..Default::default()
            },
            spec: Some(k8s_openapi::api::batch::v1::JobSpec {
                ttl_seconds_after_finished: Some(config.job.ttl_seconds_after_finished),
                backoff_limit: Some(config.job.backoff_limit),
                active_deadline_seconds: Some(config.job.timeout),
                template: k8s_openapi::api::core::v1::PodTemplateSpec {
                    spec: Some(PodSpec {
                        containers: vec![Container {
                            name: "script".to_string(),
                            image: Some(config.job.image.clone()),
                            image_pull_policy: Some(config.job.image_pull_policy.clone()),
                            command: Some(vec!["/bin/sh".to_string(), "-c".to_string(), command]),
                            env: if env_vars.is_empty() {
                                None
                            } else {
                                Some(env_vars)
                            },
                            resources,
                            volume_mounts: Some(vec![VolumeMount {
                                name: "script".to_string(),
                                mount_path: "/scripts".to_string(),
                                read_only: Some(true),
                                ..Default::default()
                            }]),
                            ..Default::default()
                        }],
                        volumes: Some(vec![Volume {
                            name: "script".to_string(),
                            config_map: Some(k8s_openapi::api::core::v1::ConfigMapVolumeSource {
                                name: configmap_name.to_string(),
                                ..Default::default()
                            }),
                            ..Default::default()
                        }]),
                        restart_policy: Some("Never".to_string()),
                        ..Default::default()
                    }),
                    ..Default::default()
                },
                ..Default::default()
            }),
            ..Default::default()
        };

        jobs.create(&PostParams::default(), &job)
            .await
            .map_err(|e| ToolError::Configuration(format!("Failed to create Job: {}", e)))
    }

    /// Wait for job completion.
    async fn wait_for_job(
        &self,
        client: &Client,
        namespace: &str,
        job_name: &str,
        timeout_secs: i64,
    ) -> Result<JobResult, ToolError> {
        let jobs: Api<Job> = Api::namespaced(client.clone(), namespace);
        let start = std::time::Instant::now();
        let timeout = std::time::Duration::from_secs(timeout_secs as u64);

        loop {
            if start.elapsed() > timeout {
                return Ok(JobResult {
                    status: "timeout".to_string(),
                    succeeded: 0,
                    failed: 1,
                    exit_code: None,
                });
            }

            match jobs.get(job_name).await {
                Ok(job) => {
                    if let Some(status) = job.status {
                        let succeeded = status.succeeded.unwrap_or(0);
                        let failed = status.failed.unwrap_or(0);

                        if succeeded > 0 {
                            return Ok(JobResult {
                                status: "completed".to_string(),
                                succeeded,
                                failed,
                                exit_code: Some(0),
                            });
                        }

                        if failed > 0 {
                            return Ok(JobResult {
                                status: "failed".to_string(),
                                succeeded,
                                failed,
                                exit_code: Some(1),
                            });
                        }
                    }
                }
                Err(e) => {
                    tracing::warn!("Error checking job status: {}", e);
                }
            }

            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        }
    }

    /// Get the pod name for a job.
    async fn get_job_pod(
        &self,
        client: &Client,
        namespace: &str,
        job_name: &str,
    ) -> Result<Option<String>, ToolError> {
        let pods: Api<Pod> = Api::namespaced(client.clone(), namespace);
        let lp = ListParams::default().labels(&format!("job-name={}", job_name));

        match pods.list(&lp).await {
            Ok(pod_list) => Ok(pod_list
                .items
                .first()
                .and_then(|p| p.metadata.name.clone())),
            Err(_) => Ok(None),
        }
    }

    /// Get logs from a pod.
    async fn get_pod_logs(
        &self,
        client: &Client,
        namespace: &str,
        pod_name: &str,
    ) -> Result<String, ToolError> {
        let pods: Api<Pod> = Api::namespaced(client.clone(), namespace);

        pods.logs(pod_name, &kube::api::LogParams::default())
            .await
            .map_err(|e| ToolError::Process(format!("Failed to get pod logs: {}", e)))
    }

    /// Clean up resources.
    async fn cleanup_resources(
        &self,
        client: &Client,
        namespace: &str,
        configmap_name: &str,
        secret_name: Option<&str>,
    ) -> Result<(), ToolError> {
        let configmaps: Api<ConfigMap> = Api::namespaced(client.clone(), namespace);
        let _ = configmaps
            .delete(configmap_name, &DeleteParams::default())
            .await;

        if let Some(sn) = secret_name {
            let secrets: Api<Secret> = Api::namespaced(client.clone(), namespace);
            let _ = secrets.delete(sn, &DeleteParams::default()).await;
        }

        Ok(())
    }

    /// Parse script config from tool config.
    fn parse_config(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ScriptConfig, ToolError> {
        let template_ctx = ctx.to_template_context();
        let rendered_config = self
            .template_engine
            .render_value(&config.config, &template_ctx)?;

        serde_json::from_value(rendered_config)
            .map_err(|e| ToolError::Configuration(format!("Invalid script config: {}", e)))
    }
}

/// Internal job result.
struct JobResult {
    status: String,
    succeeded: i32,
    failed: i32,
    exit_code: Option<i32>,
}

impl Default for ScriptTool {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for ScriptTool {
    fn name(&self) -> &'static str {
        "script"
    }

    async fn execute(
        &self,
        config: &ToolConfig,
        ctx: &ExecutionContext,
    ) -> Result<ToolResult, ToolError> {
        let script_config = self.parse_config(config, ctx)?;

        tracing::debug!(
            image = %script_config.job.image,
            namespace = %script_config.job.namespace,
            timeout = script_config.job.timeout,
            "Executing script as K8s job"
        );

        self.execute_script(&script_config, ctx).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_script_config_deserialization() {
        let json = serde_json::json!({
            "script": {
                "type": "inline",
                "content": "print('Hello, World!')"
            },
            "job": {
                "image": "python:3.11-slim",
                "namespace": "default",
                "timeout": 300
            },
            "args": {
                "name": "test"
            }
        });

        let config: ScriptConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.job.image, "python:3.11-slim");
        assert_eq!(config.job.namespace, "default");
        assert_eq!(config.job.timeout, 300);
    }

    #[test]
    fn test_script_config_defaults() {
        let json = serde_json::json!({
            "script": {
                "type": "inline",
                "content": "print('test')"
            }
        });

        let config: ScriptConfig = serde_json::from_value(json).unwrap();
        assert_eq!(config.job.image, "python:3.11-slim");
        assert_eq!(config.job.namespace, "noetl");
        assert_eq!(config.job.timeout, 600);
        assert_eq!(config.job.ttl_seconds_after_finished, 300);
    }

    #[test]
    fn test_job_config_with_resources() {
        let json = serde_json::json!({
            "script": {
                "type": "inline",
                "content": "print('test')"
            },
            "job": {
                "resources": {
                    "requests": {
                        "memory": "256Mi",
                        "cpu": "500m"
                    },
                    "limits": {
                        "memory": "512Mi",
                        "cpu": "1000m"
                    }
                }
            }
        });

        let config: ScriptConfig = serde_json::from_value(json).unwrap();
        assert_eq!(
            config.job.resources.requests.get("memory"),
            Some(&"256Mi".to_string())
        );
        assert_eq!(
            config.job.resources.limits.get("cpu"),
            Some(&"1000m".to_string())
        );
    }

    #[test]
    fn test_script_result_serialization() {
        let result = ScriptResultData {
            status: "completed".to_string(),
            job_name: "noetl-script-123".to_string(),
            namespace: "noetl".to_string(),
            pod_name: Some("noetl-script-123-abc".to_string()),
            execution_time: 5.5,
            output: Some("Hello, World!".to_string()),
            succeeded: 1,
            failed: 0,
            exit_code: Some(0),
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("completed"));
        assert!(json.contains("noetl-script-123"));
    }

    #[tokio::test]
    async fn test_script_tool_interface() {
        let tool = ScriptTool::new();
        assert_eq!(tool.name(), "script");
    }
}
