/*
 * Playbook Editor Component
 *
 * This component provides a code editor for editing YAML playbooks.
 * Currently uses an enhanced TextArea with VS Code-like features.
 *
 * To upgrade to full Monaco Editor (VS Code editor):
 * 1. Install Monaco Editor: npm install @monaco-editor/react
 * 2. Replace the CodeEditor component with Monaco Editor
 * 3. Uncomment the Monaco-specific features below
 *
 * Features:
 * - Syntax highlighting (basic in TextArea, full in Monaco)
 * - Auto-indentation with Tab key
 * - Keyboard shortcuts (Ctrl/Cmd + S to save)
 * - Fullscreen mode
 * - Dark theme
 * - Monospace font with programming ligatures
 */

import React, { useState, useEffect, useRef } from "react";
import {
  Layout,
  Button,
  Input,
  Typography,
  Space,
  Spin,
  Alert,
  Card,
  Row,
  Col,
  message,
  Divider,
} from "antd";
import {
  SaveOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  ExpandOutlined,
  CompressOutlined,
  NodeIndexOutlined,
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { PlaybookData } from "../types";
import MonacoEditor from "@monaco-editor/react";
import FlowVisualization from "./FlowVisualization";

const { Content } = Layout;
const { Title, Text } = Typography;
const { TextArea } = Input;

// Enhanced CodeEditor component with Monaco-like features using TextArea
const CodeEditor: React.FC<{
  value: string;
  onChange: (value: string) => void;
  language?: string;
  theme?: string;
  height?: number;
  isFullscreen?: boolean;
}> = ({ value, onChange, height = 500, isFullscreen = false }) => {
  const textareaRef = useRef<any>(null);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Handle Ctrl/Cmd + S for save
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      // This will be handled by the parent component
      return;
    }

    // Handle Tab for indentation
    if (e.key === "Tab") {
      e.preventDefault();
      const textarea = textareaRef.current;
      if (textarea) {
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const newValue =
          value.substring(0, start) + "  " + value.substring(end);
        onChange(newValue);

        // Set cursor position after the tab
        setTimeout(() => {
          textarea.selectionStart = textarea.selectionEnd = start + 2;
        }, 0);
      }
    }
  };

  return (
    <TextArea
      ref={textareaRef}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      placeholder="Enter your playbook YAML content here..."
      style={{
        fontFamily:
          'Monaco, "Fira Code", "Cascadia Code", "Consolas", monospace',
        fontSize: "14px",
        lineHeight: "1.5",
        height: isFullscreen ? "90vh" : `${height}px`,
        resize: "none",
        backgroundColor: "#1e1e1e",
        color: "#d4d4d4",
        border: "1px solid #3c3c3c",
        borderRadius: "4px",
        padding: "16px",
      }}
    />
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
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [editorHeight, setEditorHeight] = useState(500);
  const [showFlowVisualization, setShowFlowVisualization] = useState(false);
  const editorRef = useRef<any>(null);

  // Get playbooks ID from URL parameters
  const urlParams = new URLSearchParams(window.location.search);
  const playbookId = urlParams.get("id");
  console.log("Playbook ID from URL:", playbookId);

  useEffect(() => {
    if (playbookId) {
      loadPlaybook(playbookId);
    } else {
      // Create new playbooks template
      setContent(`# New Playbook
name: "untitled-playbook"
description: "Enter description here"
tasks:
  - name: "sample-task"
    type: "log"
    config:
      message: "Hello from NoETL!"
`);
    }
  }, [playbookId]);

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen);
    setEditorHeight(isFullscreen ? 500 : window.innerHeight - 200);
  };

  const loadPlaybook = async (id: string) => {
    try {
      setLoading(true);
      setError(null);

      const [playbookData, playbookContent] = await Promise.all([
        apiService.getPlaybook(id),
        apiService.getPlaybookContent(id),
      ]);

      setPlaybook(playbookData);
      setContent(playbookContent);
    } catch (err: any) {
      console.error("Failed to load playbooks:", err);
      // IMPROVEMENT: Display the specific error from the server
      const detail =
        err.response?.data?.detail ||
        "An unknown error occurred. Check the server logs.";
      const status = err.response?.status
        ? ` (Status: ${err.response.status})`
        : "";
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
        // Update existing playbooks
        await apiService.savePlaybookContent(playbookId, content);
        message.success("Playbook saved successfully");
      } else {
        // Create new playbooks
        const newPlaybook = await apiService.createPlaybook({
          name: "New Playbook",
          description: "Created from editor",
          status: "draft",
        });
        await apiService.savePlaybookContent(newPlaybook.id, content);
        setPlaybook(newPlaybook);
        window.history.pushState({}, "", `/editor?id=${newPlaybook.id}`);
        message.success("New playbooks created and saved");
      }
    } catch (err) {
      console.error("Failed to save playbooks:", err);
      message.error("Failed to save playbooks");
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
    } catch (err) {
      console.error("Validation failed:", err);
      message.error("Validation failed");
    } finally {
      setValidating(false);
    }
  };

  const handleExecute = async () => {
    if (!playbook) {
      message.error("Please save the playbooks first");
      return;
    }

    try {
      setExecuting(true);
      await apiService.executePlaybook(playbook.id);
      message.success("Playbook execution started");
      // Redirect to execution page
      window.location.href = "/execution";
    } catch (err) {
      console.error("Failed to execute playbooks:", err);
      message.error("Failed to execute playbooks");
    } finally {
      setExecuting(false);
    }
  };

  const handleShowWorkflow = () => {
    setShowFlowVisualization(true);
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
      <Space className="PlaybookEditor__content" direction="vertical" size="large" style={{ width: "100%" }}>
        <Row className="PlaybookEditor__header" justify="space-between" align="middle">
          <Col>
            <Title level={2}>✏️ Playbook Editor</Title>
            {playbook ? (
              <Text type="secondary">
                Editing: {playbook.name} (ID:{" "}
                {playbookId || playbook.id || "New"})
              </Text>
            ) : playbookId ? (
              <Text type="secondary">
                Loading playbook (ID: {playbookId})...
              </Text>
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
                type="default"
                icon={<NodeIndexOutlined />}
                onClick={handleShowWorkflow}
                disabled={!content.trim()}
                title="Show workflow visualization"
              >
                Show Workflow
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                onClick={handleSave}
              >
                Save
              </Button>
              <Button
                type="default"
                icon={<PlayCircleOutlined />}
                loading={executing}
                onClick={handleExecute}
                disabled={!playbook}
              >
                Execute
              </Button>
            </Space>
          </Col>
        </Row>

        {/* Validation Results */}
        {validationResult && (
          <Card className="PlaybookValidationErrors" size="small">
            <Alert
              message={
                validationResult.valid
                  ? "Playbook is valid"
                  : "Validation failed"
              }
              description={
                validationResult.errors &&
                  validationResult.errors.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    {validationResult.errors.map((error, index) => (
                      <li key={index}>{error}</li>
                    ))}
                  </ul>
                ) : undefined
              }
              type={validationResult.valid ? "success" : "error"}
              showIcon
            />
          </Card>
        )}

        {/* Flow Visualization (embedded above the code editor when requested) */}
        <FlowVisualization
          visible={showFlowVisualization}
          onClose={() => setShowFlowVisualization(false)}
          playbookId={playbookId || playbook?.id || "new"}
          playbookName={playbook?.name || "New Playbook"}
          content={content}
          onUpdateContent={(newYaml) => setContent(newYaml)}
        />

        {/* Code Editor */}
        <Card className="YamlEditor" style={{ height: isFullscreen ? "100vh" : "auto", padding: 0 }}>
          <MonacoEditor
            height={isFullscreen ? "90vh" : editorHeight}
            language="yaml"
            theme="light"
            value={content}
            onChange={(value: any) => setContent(value || "")}
            options={{
              selectOnLineNumbers: true,
              mouseWheelZoom: true,
              formatOnPaste: true,
              formatOnType: true,
              automaticLayout: true,
              minimap: { enabled: !isFullscreen },
              wordWrap: "on",
              lineNumbers: "on",
              folding: true,
              matchBrackets: "always",
              autoIndent: "full",
              tabSize: 2,
              insertSpaces: true,
            }}
          />
        </Card>

        {/* Help text */}
        <Card size="small">
          <Text type="secondary">
            <strong>Tips:</strong> Use YAML format for playbook definition.
            Validate your playbook before saving to catch syntax errors. Use{" "}
            <kbd>Ctrl/Cmd + S</kbd> to save quickly.
          </Text>
        </Card>
      </Space>
    </Content>
  );
};

export default PlaybookEditor;
