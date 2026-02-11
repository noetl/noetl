import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Input, Space, Tag, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import {
  connectSSE,
  disconnectSSE,
  executeGatewayPlaybook,
  getUserInfo,
  isAuthenticated,
  logout,
  subscribeConnection,
  subscribeProgress,
  validateSession,
} from "../services/gatewayAuth";
import "../styles/Gateway.css";

const { Title, Text } = Typography;

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  status?: string;
  executionId?: string;
};

const suggestions = [
  "I want to fly from SFO to JFK tomorrow",
  "Find flights from New York to London next Friday",
  "Show cheapest options from LAX to Tokyo this weekend",
];

function messageId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const GatewayAssistant = () => {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [connectionReady, setConnectionReady] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const user = useMemo(() => getUserInfo(), []);

  useEffect(() => {
    const initialize = async () => {
      if (!isAuthenticated()) {
        navigate("/gateway/login", { replace: true });
        return;
      }

      try {
        const valid = await validateSession();
        if (!valid) {
          logout();
          navigate("/gateway/login", { replace: true });
          return;
        }
      } catch {
        logout();
        navigate("/gateway/login", { replace: true });
        return;
      }

      connectSSE();
    };

    const unsubscribeConnection = subscribeConnection((connected) => {
      setConnectionReady(connected);
    });
    const unsubscribeProgress = subscribeProgress((message) => {
      setProgress(message);
    });

    initialize();

    return () => {
      unsubscribeConnection();
      unsubscribeProgress();
      disconnectSSE();
    };
  }, [navigate]);

  const appendMessage = (message: ChatMessage) => {
    setMessages((previous) => [...previous, message]);
  };

  const onSubmit = async (prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed || submitting) {
      return;
    }

    if (!connectionReady) {
      setError("Real-time connection is not ready yet. Please wait a moment.");
      return;
    }

    setError(null);
    setProgress(null);
    setSubmitting(true);
    setQuery("");
    appendMessage({ id: messageId(), role: "user", text: trimmed });

    try {
      const result = await executeGatewayPlaybook(trimmed);
      appendMessage({
        id: messageId(),
        role: "assistant",
        text: result.textOutput || "No response returned by the playbook.",
        status: result.status,
        executionId: result.executionId || result.id,
      });
    } catch (submitError) {
      const detail = submitError instanceof Error ? submitError.message : "Failed to execute playbook";
      if (detail === "Session expired" || detail === "Not authenticated") {
        logout();
        navigate("/gateway/login", { replace: true });
        return;
      }
      setError(detail);
    } finally {
      setSubmitting(false);
      setProgress(null);
    }
  };

  return (
    <div className="gateway-assistant-wrap">
      <Card className="gateway-assistant-card" bordered={false}>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <div className="gateway-header">
            <div>
              <Title level={3} style={{ marginBottom: 4 }}>
                Amadeus Gateway Assistant
              </Title>
              <Text type="secondary">
                Ask flight-search queries and execute playbook `api_integration/amadeus_ai_api`.
              </Text>
            </div>
            <Space>
              <Tag color={connectionReady ? "green" : "orange"}>
                {connectionReady ? "Connected" : "Connecting"}
              </Tag>
              <Text type="secondary">
                {user?.display_name || user?.email || "Authenticated user"}
              </Text>
              <Button
                onClick={() => {
                  logout();
                  navigate("/gateway/login", { replace: true });
                }}
              >
                Logout
              </Button>
            </Space>
          </div>

          {error && (
            <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} />
          )}

          <div className="gateway-chat-log">
            {messages.length === 0 && (
              <div className="gateway-chat-empty">
                <Text type="secondary">
                  Start by entering a travel request, or use one of the quick suggestions.
                </Text>
              </div>
            )}
            {messages.map((message) => (
              <div key={message.id} className={`gateway-message ${message.role}`}>
                <div className="gateway-message-content">
                  <Text>{message.text}</Text>
                  {(message.executionId || message.status) && (
                    <div className="gateway-message-meta">
                      {message.executionId && <Text type="secondary">Execution: {message.executionId}</Text>}
                      {message.status && <Tag>{message.status}</Tag>}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {submitting && (
              <div className="gateway-message assistant">
                <div className="gateway-message-content">
                  <Text type="secondary">{progress || "Processing request..."}</Text>
                </div>
              </div>
            )}
          </div>

          <Space wrap>
            {suggestions.map((item) => (
              <Button key={item} size="small" onClick={() => onSubmit(item)} disabled={submitting}>
                {item}
              </Button>
            ))}
          </Space>

          <Input.Search
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask about flights..."
            enterButton="Send"
            loading={submitting}
            onSearch={onSubmit}
          />
        </Space>
      </Card>
    </div>
  );
};

export default GatewayAssistant;
