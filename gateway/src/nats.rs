use std::sync::Arc;

use anyhow::Context;
use async_nats::Client;
use futures::{Stream, StreamExt};

#[derive(Clone)]
pub struct Nats {
    client: Arc<Client>,
}

impl Nats {
    pub async fn connect(url: &str) -> anyhow::Result<Self> {
        let client = async_nats::connect(url).await.context("connect to NATS")?;
        Ok(Self { client: Arc::new(client) })
    }

    pub async fn subscribe_json(&self, subject: String) -> anyhow::Result<impl Stream<Item = serde_json::Value>> {
        let sub = self.client.subscribe(subject).await.context("nats subscribe")?;
        let stream = sub.filter_map(|msg| async move {
            match serde_json::from_slice::<serde_json::Value>(&msg.payload) {
                Ok(v) => Some(v),
                Err(e) => {
                    tracing::warn!(error = %e, "failed to parse JSON from NATS message");
                    None
                }
            }
        });
        Ok(stream)
    }
}
