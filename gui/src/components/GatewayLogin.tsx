import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Divider, Form, Input, Space, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import {
  getAuth0AuthorizeUrl,
  getUserInfo,
  isAuthenticated,
  loginWithAuth0Token,
  validateSession,
} from "../services/gatewayAuth";
import "../styles/Gateway.css";

const { Title, Text } = Typography;

function parseHashIdToken(): string | null {
  const hash = window.location.hash;
  if (!hash || hash.length < 2) {
    return null;
  }
  const params = new URLSearchParams(hash.slice(1));
  return params.get("id_token");
}

const GatewayLogin = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const auth0Url = useMemo(() => getAuth0AuthorizeUrl(), []);

  useEffect(() => {
    const initialize = async () => {
      if (isAuthenticated() && getUserInfo()) {
        navigate("/", { replace: true });
        return;
      }

      const idToken = parseHashIdToken();
      if (!idToken) {
        return;
      }

      setLoading(true);
      try {
        await loginWithAuth0Token(idToken);
        setMessage({ type: "success", text: "Login successful. Redirecting..." });
        navigate("/", { replace: true });
      } catch (error) {
        const detail = error instanceof Error ? error.message : "Authentication failed";
        setMessage({ type: "error", text: detail });
      } finally {
        if (window.location.hash) {
          window.history.replaceState({}, document.title, window.location.pathname);
        }
        setLoading(false);
      }
    };

    initialize();
  }, [navigate]);

  const onTokenLogin = async (values: { session_token: string }) => {
    setTokenLoading(true);
    setMessage(null);
    try {
      const ok = await validateSession(values.session_token.trim());
      if (!ok) {
        throw new Error("Invalid or expired session token");
      }
      setMessage({ type: "success", text: "Session validated. Redirecting..." });
      navigate("/", { replace: true });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Token login failed";
      setMessage({ type: "error", text: detail });
    } finally {
      setTokenLoading(false);
    }
  };

  return (
    <div className="gateway-login-wrap">
      <Card className="gateway-login-card" bordered={false}>
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              Gateway Login
            </Title>
            <Text type="secondary">
              Authenticate with Auth0 or validate an existing session token.
            </Text>
          </div>

          {message && (
            <Alert
              type={message.type}
              message={message.text}
              showIcon
              closable
              onClose={() => setMessage(null)}
            />
          )}

          <Button
            type="primary"
            size="large"
            block
            loading={loading}
            onClick={() => {
              window.location.href = auth0Url;
            }}
          >
            Sign In with Auth0
          </Button>

          <Divider plain>OR</Divider>

          <Form layout="vertical" onFinish={onTokenLogin}>
            <Form.Item
              label="Session Token"
              name="session_token"
              rules={[{ required: true, message: "Session token is required" }]}
            >
              <Input placeholder="Paste session token for testing" />
            </Form.Item>
            <Button
              type="default"
              htmlType="submit"
              block
              loading={tokenLoading}
            >
              Sign In with Token
            </Button>
          </Form>
        </Space>
      </Card>
    </div>
  );
};

export default GatewayLogin;
