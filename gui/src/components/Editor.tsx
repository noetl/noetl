import React, { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Layout,
  Row,
  Space,
  Spin,
  Tabs,
  Typography,
  message,
} from "antd";
import {
  ApartmentOutlined,
  CheckCircleOutlined,
  CodeOutlined,
  ExperimentOutlined,
  PlayCircleOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import MonacoEditor from "@monaco-editor/react";
import { useNavigate } from "react-router-dom";
// @ts-ignore
import yaml from "js-yaml";
import { apiService } from "../services/api";
import { PlaybookData } from "../types";
import PlaybookDesigner from "./PlaybookDesigner";
import PlaybookTestLab from "./PlaybookTestLab";

const { Content } = Layout;
const { Title, Text } = Typography;

const stripYamlExtension = (value: string): string => value.replace(/\.(ya?ml)$/i, "");

const normalizeCatalogPath = (value: string): string => {
  const parts = value
    .split("/")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  const stack: string[] = [];
  for (const part of parts) {
    if (part === ".") continue;
    if (part === "..") {
      if (stack.length > 0) stack.pop();
      continue;
    }
    stack.push(part);
  }
  return stack.join("/");
};

const resolveRelativeCatalogPath = (referencePath: string, currentPath?: string | null): string => {
  const ref = referencePath.trim();
  if (!ref.startsWith("./") && !ref.startsWith("../")) {
    return normalizeCatalogPath(ref);
  }
  const current = normalizeCatalogPath(String(currentPath || ""));
  if (!current) return normalizeCatalogPath(ref);
  const baseParts = current.split("/");
  baseParts.pop();
  const merged = [...baseParts, ...ref.split("/")].join("/");
  return normalizeCatalogPath(merged);
};

const buildReferenceCandidates = (referencePath: string, currentPath?: string | null): string[] => {
  const ref = referencePath.trim();
  if (!ref) return [];
  const candidates = [
    ref,
    stripYamlExtension(ref),
    resolveRelativeCatalogPath(ref, currentPath),
    stripYamlExtension(resolveRelativeCatalogPath(ref, currentPath)),
  ];
  return Array.from(
    new Set(
      candidates
        .map((candidate) => normalizeCatalogPath(candidate))
        .filter((candidate) => candidate.length > 0)
    )
  );
};

const PlaybookEditor: React.FC = () => {
  const [playbook, setPlaybook] = useState<PlaybookData | null>(null);
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors?: string[];
  } | null>(null);
  const [activeTab, setActiveTab] = useState("designer");
  const navigate = useNavigate();

  const urlParams = new URLSearchParams(window.location.search);
  const playbookId = urlParams.get("id");

  useEffect(() => {
    if (playbookId) {
      loadPlaybook(playbookId);
    } else {
      setContent(`apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: new_playbook
  path: examples/new_playbook
  version: "1.0"
  description: New playbook
workload: {}
workflow: []
`);
    }
  }, [playbookId]);

  const loadPlaybook = async (id: string) => {
    try {
      setLoading(true);
      setError(null);
      const playbookData = await apiService.getPlaybook(id);
      setPlaybook(playbookData);
      setContent(playbookData.content || "");
    } catch (err: any) {
      const detail =
        err.response?.data?.detail ||
        "Unknown error while loading playbook. Check gateway/noetl logs.";
      const status = err.response?.status ? ` (Status: ${err.response.status})` : "";
      setError(`Failed to load playbook content: ${detail}${status}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!content.trim()) {
      message.error("Playbook content cannot be empty");
      return;
    }

    try {
      setSaving(true);
      if (playbookId) {
        await apiService.savePlaybookContent(playbookId, content);
        message.success("Playbook saved successfully");
      } else {
        const created = await apiService.createPlaybook(content);
        navigate(`/editor?id=${created.path}`);
        message.success(created.message || "Playbook created");
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "Failed to save playbook");
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    try {
      setValidating(true);
      const result = await apiService.validatePlaybook(content);
      setValidationResult(result);
      if (result.valid) {
        message.success("Playbook is valid");
      } else {
        message.error("Playbook validation failed");
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "Validation failed");
    } finally {
      setValidating(false);
    }
  };

  const extractExecutionTarget = (): { path?: string; version?: string } => {
    if (playbook?.path) {
      return { path: playbook.path, version: playbook.version };
    }
    try {
      const loaded = (yaml.load(content) || {}) as any;
      return {
        path: loaded?.metadata?.path,
        version: String(loaded?.metadata?.version || "latest"),
      };
    } catch {
      return {};
    }
  };

  const handleExecute = async () => {
    const target = extractExecutionTarget();
    if (!target.path) {
      message.error("metadata.path is required to execute this playbook");
      return;
    }

    try {
      setExecuting(true);
      const response = await apiService.executePlaybookWithPayload({
        path: target.path,
        version: target.version || "latest",
        payload: {},
      });
      message.success(`Execution started. ID: ${response.execution_id}`);
      navigate(`/execution/${response.execution_id}`);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || "Failed to execute playbook");
    } finally {
      setExecuting(false);
    }
  };

  const resolveCurrentCatalogPath = (): string | null => {
    if (playbook?.path) return playbook.path;
    if (playbookId) return playbookId;
    try {
      const loaded = (yaml.load(content) || {}) as any;
      const metadataPath = loaded?.metadata?.path;
      return typeof metadataPath === "string" && metadataPath.trim() ? metadataPath.trim() : null;
    } catch {
      return null;
    }
  };

  const handleDrillDownPlaybook = async (referencePath: string) => {
    const currentPath = resolveCurrentCatalogPath();
    const candidates = buildReferenceCandidates(referencePath, currentPath);
    if (candidates.length === 0) {
      message.error("Referenced playbook path is empty");
      return;
    }

    let resolvedPath: string | null = null;
    for (const candidate of candidates) {
      try {
        await apiService.getPlaybook(candidate);
        resolvedPath = candidate;
        break;
      } catch {
        // Try next candidate
      }
    }

    if (!resolvedPath) {
      message.error(`Referenced playbook not found: ${referencePath}`);
      return;
    }

    const query = new URLSearchParams({ id: resolvedPath }).toString();
    navigate(`/editor?${query}`);
  };

  if (loading) {
    return (
      <Content style={{ padding: "50px", textAlign: "center" }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>Loading editor...</div>
      </Content>
    );
  }

  if (error) {
    return (
      <Content style={{ padding: "50px" }}>
        <Alert message="Error" description={error} type="error" showIcon />
      </Content>
    );
  }

  return (
    <Content className="PlaybookEditor">
      <Space
        className="PlaybookEditor__content"
        direction="vertical"
        size="large"
        style={{ width: "100%" }}
      >
        <Row className="PlaybookEditor__header" justify="space-between" align="middle">
          <Col>
            <Title level={2}>Playbook Studio</Title>
            {playbook ? (
              <Text type="secondary">
                Editing: {playbook.path} (ID: {playbookId || playbook.catalog_id || "new"})
              </Text>
            ) : playbookId ? (
              <Text type="secondary">Loading playbook (ID: {playbookId})...</Text>
            ) : (
              <Text type="secondary">Creating new playbook</Text>
            )}
          </Col>
          <Col>
            <Space>
              <Button
                type="default"
                icon={<CheckCircleOutlined />}
                loading={validating}
                onClick={handleValidate}
              >
                Validate
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                onClick={handleSave}
                data-e2e="save-playbook-button"
              >
                Save
              </Button>
              <Button
                type="default"
                icon={<PlayCircleOutlined />}
                loading={executing}
                onClick={handleExecute}
                disabled={!content.trim()}
              >
                Execute
              </Button>
            </Space>
          </Col>
        </Row>

        {validationResult && (
          <Card className="PlaybookValidationErrors" size="small">
            <Alert
              message={validationResult.valid ? "Playbook is valid" : "Validation failed"}
              description={
                validationResult.errors && validationResult.errors.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    {validationResult.errors.map((entry, index) => (
                      <li key={index}>{entry}</li>
                    ))}
                  </ul>
                ) : undefined
              }
              type={validationResult.valid ? "success" : "error"}
              showIcon
            />
          </Card>
        )}

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "designer",
              label: (
                <span>
                  <ApartmentOutlined /> Designer
                </span>
              ),
              children: (
                <PlaybookDesigner
                  yamlContent={content}
                  onYamlChange={setContent}
                  playbookId={playbookId || playbook?.path || null}
                  onDrillDownPlaybook={handleDrillDownPlaybook}
                />
              ),
            },
            {
              key: "yaml",
              label: (
                <span>
                  <CodeOutlined /> YAML
                </span>
              ),
              children: (
                <Card className="YamlEditor" bodyStyle={{ padding: 0 }}>
                  <MonacoEditor
                    height="68vh"
                    language="yaml"
                    theme="light"
                    value={content}
                    onChange={(value: any) => setContent(value || "")}
                    options={{
                      automaticLayout: true,
                      minimap: { enabled: true },
                      wordWrap: "on",
                      lineNumbers: "on",
                      folding: true,
                      matchBrackets: "always",
                      autoIndent: "full",
                      tabSize: 2,
                      insertSpaces: true,
                      formatOnPaste: true,
                      formatOnType: true,
                    }}
                  />
                </Card>
              ),
            },
            {
              key: "tests",
              label: (
                <span>
                  <ExperimentOutlined /> Tests
                </span>
              ),
              children: <PlaybookTestLab yamlContent={content} playbook={playbook} />,
            },
          ]}
        />
      </Space>
    </Content>
  );
};

export default PlaybookEditor;
