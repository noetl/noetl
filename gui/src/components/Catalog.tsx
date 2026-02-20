import React, { useState, useEffect, useCallback } from "react";
import {
  Layout,
  Row,
  Col,
  Input,
  Card,
  Button,
  Typography,
  Space,
  Spin,
  Alert,
  Tag,
  message,
  Modal,
  Tabs,
  Upload,
  Checkbox,
} from "antd";
import {
  SearchOutlined,
  PlayCircleOutlined,
  EditOutlined,
  EyeOutlined,
  FileTextOutlined,
  UploadOutlined,
  PlusOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { PlaybookData } from "../types";
import "../styles/Catalog.css";
import { useNavigate } from "react-router-dom";
import { AxiosError } from "axios";

const { Content } = Layout;
const { Title, Text } = Typography;
const { Search } = Input;
const { TextArea } = Input;
const { TabPane } = Tabs;

const Catalog: React.FC = () => {
  const navigate = useNavigate();
  const [playbooks, setPlaybooks] = useState<PlaybookData[]>([]);
  const [allPlaybooks, setAllPlaybooks] = useState<PlaybookData[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  // Payload modal state
  const [payloadModalVisible, setPayloadModalVisible] = useState(false);
  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string | null>(
    null,
  );
  const [selectedPlaybookVersion, setSelectedPlaybookVersion] = useState<
    string | null
  >(null);
  const [selectedCatalogId, setSelectedCatalogId] = useState<string | null>(
    null,
  );
  const [payloadJson, setPayloadJson] = useState("");
  const [payloadFile, setPayloadFile] = useState<File | null>(null);
  const [mergePayload, setMergePayload] = useState(false);
  const [activePayloadTab, setActivePayloadTab] = useState("json");

  // Create playbook modal state
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [createPlaybookJson, setCreatePlaybookJson] = useState("");
  const [createPlaybookFile, setCreatePlaybookFile] = useState<File | null>(null);
  const [activeCreateTab, setActiveCreateTab] = useState("json");
  const [createPlaybookAiPrompt, setCreatePlaybookAiPrompt] = useState("");
  const [createPlaybookAiDraft, setCreatePlaybookAiDraft] = useState("");
  const [createPlaybookAiResult, setCreatePlaybookAiResult] = useState<any | null>(null);
  const [generatingPlaybookAi, setGeneratingPlaybookAi] = useState(false);

  // Explain playbook modal state
  const [explainingPlaybookPath, setExplainingPlaybookPath] = useState<string | null>(null);
  const [explainModalVisible, setExplainModalVisible] = useState(false);
  const [explainResult, setExplainResult] = useState<any | null>(null);

  // Debounced search function
  const debounceSearch = useCallback(
    (() => {
      let timeoutId: number;
      return (query: string) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          handleSearchInternal(query);
        }, 300);
      };
    })(),
    [allPlaybooks],
  );

  const handleSearchInternal = useCallback(
    async (query: string) => {
      if (!query.trim()) {
        // If empty search, show all playbooks
        setPlaybooks(allPlaybooks);
        return;
      }

      try {
        setSearchLoading(true);

        // Try server-side search first
        try {
          const results = await apiService.searchPlaybooks(query);
          setPlaybooks(results);
        } catch (serverError) {
          // Fallback to client-side search if server search fails
          console.warn(
            "Server search failed, falling back to client-side search:",
            serverError,
          );
          const filteredPlaybooks = allPlaybooks.filter(
            (playbook) =>
              playbook.path.toLowerCase().includes(query.toLowerCase()) ||
              (playbook.payload?.metadata?.description &&
                playbook.payload.metadata.description
                  .toLowerCase()
                  .includes(query.toLowerCase())),
          );
          setPlaybooks(filteredPlaybooks);
        }
      } catch (err) {
        console.error("Search failed:", err);
        message.error("Search failed. Please try again.");
      } finally {
        setSearchLoading(false);
      }
    },
    [allPlaybooks],
  );

  const handleSearch = (query: string) => {
    handleSearchInternal(query);
  };

  useEffect(() => {
    fetchCatalogData();
  }, []);

  const fetchCatalogData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch playbooks and catalog widgets from FastAPI
      const playbooksResponse = await apiService.getPlaybooks();

      setPlaybooks(playbooksResponse);
      setAllPlaybooks(playbooksResponse); // Store all playbooks for local filtering
    } catch (err) {
      console.error("Failed to fetch catalog data:", err);
      setError(
        "Failed to load catalog data. Please check if the server is running.",
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSearchInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchQuery(value);
    debounceSearch(value);
  };

  const handleExecutePlaybook = async (catalog_id: string) => {
    try {
      let executePlaybookResponse = await apiService.executePlaybook(catalog_id);
      message.success(`Playbook execution started successfully! Execution ID: ${executePlaybookResponse.execution_id}`);

      // Navigate to execution page
      navigate(`/execution/${executePlaybookResponse.execution_id}`);
    } catch (err: AxiosError<any, any> | any) {

      if (err instanceof AxiosError && err.response) {
        const data = err.response?.data?.detail as any;
        if (data?.code === "validation_error") {
          message.error(
            `Failed to execute playbook Validation Error: ${data.error} at ${JSON.stringify(data.place, null, 2)}`,
          );
          return;
        }
        console.error("Execution API error: ", err.response?.data);
        message.error(`Failed to execute playbook. ${err.response?.data?.detail}.`);
        return;
      }
      console.error("Failed to execute playbooks:", err);
      message.error("Failed to execute playbooks. Please try again.");
    }
  };

  const handleViewPayload = (playbookId: string, version: string, catalogId: string) => {
    setSelectedPlaybookId(playbookId);
    setSelectedPlaybookVersion(version);
    setSelectedCatalogId(catalogId);
    setPayloadModalVisible(true);
    // Reset form
    setPayloadJson("");
    setPayloadFile(null);
    setMergePayload(false);
    setActivePayloadTab("json");
  };

  const handleExecuteWithPayload = async () => {
    if (!selectedCatalogId) {
      message.error("No playbook selected");
      return;
    }

    let payloadObject = null;

    try {
      if (activePayloadTab === "json" && payloadJson.trim()) {
        payloadObject = JSON.parse(payloadJson);
      } else if (activePayloadTab === "file" && payloadFile) {
        const fileText = await payloadFile.text();
        payloadObject = JSON.parse(fileText);
      }
    } catch (error) {
      message.error("Invalid JSON format. Please check your input.");
      return;
    }

    const requestBody: any = {
      catalog_id: selectedCatalogId,
      merge: mergePayload,
    };

    if (payloadObject) {
      requestBody.args = payloadObject;
    }

    try {
      setPayloadModalVisible(false);
      message.info(`Executing playbook "${selectedPlaybookId}"...`);

      const response = await apiService.executePlaybookWithPayload(requestBody);
      message.success(`Execution started. ID: ${response.execution_id}`);

      // Navigate to execution page
      navigate(`/execution/${response.execution_id}`);
    } catch (error) {
      console.error("Failed to execute playbook with payload:", error);
      message.error("Failed to execute playbook. Please try again.");
    }
  };

  const handleClosePayloadModal = () => {
    setPayloadModalVisible(false);
    setSelectedPlaybookId(null);
    setSelectedPlaybookVersion(null);
    setSelectedCatalogId(null);
    setPayloadJson("");
    setPayloadFile(null);
    setMergePayload(false);
    setActivePayloadTab("json");
  };

  const handleFileUpload = (file: File) => {
    setPayloadFile(file);
    return false; // Prevent auto upload
  };

  const handleCreatePlaybookFileUpload = (file: File) => {
    setCreatePlaybookFile(file);
    return false; // Prevent auto upload
  };

  const handleOpenCreateModal = () => {
    setCreateModalVisible(true);
    setCreatePlaybookJson("");
    setCreatePlaybookFile(null);
    setActiveCreateTab("json");
    setCreatePlaybookAiPrompt("");
    setCreatePlaybookAiDraft("");
    setCreatePlaybookAiResult(null);
  };

  const handleCloseCreateModal = () => {
    setCreateModalVisible(false);
    setCreatePlaybookJson("");
    setCreatePlaybookFile(null);
    setActiveCreateTab("json");
    setCreatePlaybookAiPrompt("");
    setCreatePlaybookAiDraft("");
    setCreatePlaybookAiResult(null);
  };

  const handleCreatePlaybook = async () => {
    let playbookContent = null;

    try {
      if (activeCreateTab === "json" && createPlaybookJson.trim()) {
        // Send the content as-is (can be JSON or YAML)
        playbookContent = createPlaybookJson.trim();
      } else if (activeCreateTab === "file" && createPlaybookFile) {
        const fileText = await createPlaybookFile.text();
        playbookContent = fileText.trim();
      } else if (activeCreateTab === "ai" && createPlaybookAiDraft.trim()) {
        playbookContent = createPlaybookAiDraft.trim();
      } else {
        message.error("Please provide playbook data");
        return;
      }
    } catch (error) {
      message.error("Failed to read playbook data.");
      return;
    }

    try {
      await apiService.registerPlaybook(playbookContent);
      message.success("Playbook registered successfully!");
      setCreateModalVisible(false);
      fetchCatalogData();
    } catch (error: any) {
      console.error("Failed to register playbook:", error);
      message.error(error?.response?.data?.detail || "Failed to register playbook. Please try again.");
    }
  };

  const handleGeneratePlaybookWithAI = async () => {
    const prompt = createPlaybookAiPrompt.trim();
    if (!prompt) {
      message.error("Please enter a prompt for AI generation");
      return;
    }

    try {
      setGeneratingPlaybookAi(true);
      const result = await apiService.generatePlaybookWithAI({
        prompt,
        timeout_seconds: 180,
        poll_interval_ms: 1500,
      });
      const generated = String(result?.generated_playbook || "").trim();
      if (!generated) {
        message.error("AI generation finished but returned empty playbook draft");
        return;
      }
      setCreatePlaybookAiDraft(generated);
      setCreatePlaybookAiResult(result);
      message.success("AI draft generated");
    } catch (error: any) {
      console.error("Failed to generate playbook with AI:", error);
      message.error(
        error?.response?.data?.detail || "Failed to generate playbook draft with AI.",
      );
    } finally {
      setGeneratingPlaybookAi(false);
    }
  };

  const handleUseAIDraftInEditor = () => {
    if (!createPlaybookAiDraft.trim()) {
      message.warning("Generate a draft first");
      return;
    }
    setCreatePlaybookJson(createPlaybookAiDraft.trim());
    setActiveCreateTab("json");
    message.success("Draft loaded into JSON/YAML editor");
  };

  const handleExplainPlaybook = async (playbook: PlaybookData) => {
    try {
      setExplainingPlaybookPath(playbook.path);
      const result = await apiService.explainPlaybookWithAI({
        catalog_id: playbook.catalog_id,
        path: playbook.path,
        version: playbook.version,
        timeout_seconds: 180,
        poll_interval_ms: 1500,
      });
      setExplainResult(result);
      setExplainModalVisible(true);
      message.success("AI explanation generated");
    } catch (error: any) {
      console.error("Failed to explain playbook with AI:", error);
      message.error(
        error?.response?.data?.detail || "Failed to explain playbook with AI.",
      );
    } finally {
      setExplainingPlaybookPath(null);
    }
  };

  const handleCloseExplainModal = () => {
    setExplainModalVisible(false);
    setExplainResult(null);
  };

  const handleViewFlow = (playbookId: string, playbookName: string) => {
    // Navigate to execution page with playbook visualization (query + state)
    navigate(`/execution?playbook=${encodeURIComponent(playbookId)}&view=workflow`, {
      state: { playbookId, view: 'workflow' }
    });
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "active":
        return "green";
      case "inactive":
        return "red";
      case "draft":
        return "orange";
      default:
        return "default";
    }
  };

  if (loading) {
    return (
      <Content className="catalog-loading-content">
        <Spin size="large" />
        <div className="catalog-loading-text">Loading catalog...</div>
      </Content>
    );
  }

  if (error) {
    return (
      <Content className="catalog-error-content">
        <Alert message="Error" description={error} type="error" showIcon />
      </Content>
    );
  }

  return (
    <Content className="catalog-main-content">
      <Space direction="vertical" size="large" className="catalog-space-vertical">
        <div className="catalog-header">
          <Title level={2}>📚 Playbook Catalog</Title>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleOpenCreateModal}
          >
            New Playbook
          </Button>
        </div>

        <Search
          placeholder="Search playbooks..."
          allowClear
          enterButton={<SearchOutlined />}
          size="large"
          loading={searchLoading}
          value={searchQuery}
          onSearch={handleSearch}
          onChange={handleSearchInputChange}
          data-pw={`catalog.search`}
        />

        {/* Playbooks list */}
        <Space direction="vertical" size="middle" className="catalog-playbooks-space">
          {playbooks.map((playbook) => (
            <Card key={playbook.catalog_id} size="small" className="catalog-playbook-card">
              <Row align="middle" gutter={16}>
                <Col flex="auto">
                  <Space
                    direction="horizontal"
                    size="large"
                    className="catalog-playbook-row"
                  >
                    <div>
                      <Title level={5} style={{ margin: 0, marginBottom: 4 }}>
                        {playbook.path.split("/").pop()}
                        <Tag
                          color={getStatusColor(playbook.status)}
                          style={{ marginLeft: 8 }}
                        >
                          {playbook.status}
                        </Tag>
                      </Title>
                      <Space direction="horizontal" size="large">
                        <Text type="secondary">Path: {playbook.path}</Text>
                        <Text type="secondary">
                          Version: {playbook.version}
                        </Text>
                        <Text type="secondary">
                          Tasks: {playbook.payload?.workflow?.length || 0}
                        </Text>
                        <Text type="secondary">
                          Updated:{" "}
                          {new Date(playbook.meta?.registered_at).toLocaleDateString()}
                        </Text>
                      </Space>
                      {playbook.payload?.metadata?.description && (
                        <div style={{ marginTop: 4 }}>
                          <Text type="secondary">{playbook.payload.metadata.description}</Text>
                        </div>
                      )}
                    </div>
                  </Space>
                </Col>
                <Col>
                  <Space>
                    <Button
                      type="text"
                      icon={<EyeOutlined />}
                      onClick={() => handleViewFlow(playbook.catalog_id, playbook.path)}
                    >
                      View
                    </Button>
                    <Button
                      type="text"
                      icon={<EditOutlined />}
                      onClick={() => navigate(`/editor?id=${playbook.path}`)}
                    >
                      Edit
                    </Button>
                    <Button
                      type="text"
                      icon={<FileTextOutlined />}
                      onClick={() =>
                        handleViewPayload(
                          playbook.path,
                          playbook.version.toString(),
                          playbook.catalog_id,
                        )
                      }
                    >
                      Payload
                    </Button>
                    <Button
                      type="text"
                      icon={<RobotOutlined />}
                      onClick={() => handleExplainPlaybook(playbook)}
                      loading={explainingPlaybookPath === playbook.path}
                    >
                      Explain with AI
                    </Button>
                    <Button
                      type="primary"
                      icon={<PlayCircleOutlined />}
                      onClick={() => handleExecutePlaybook(playbook.catalog_id)}
                      disabled={playbook.status !== "active"}
                      data-pw={`catalog.execute`}
                    >
                      Execute
                    </Button>
                  </Space>
                </Col>
              </Row>
            </Card>
          ))}
        </Space>

        {playbooks.length === 0 && !loading && (
          <Alert
            message={
              searchQuery ? "No playbooks found" : "No playbooks available"
            }
            description={
              searchQuery
                ? `No playbooks match your search for "${searchQuery}".`
                : "There are no playbooks in the catalog yet."
            }
            type="info"
            showIcon
          />
        )}
      </Space>

      {/* Payload Modal */}
      <Modal
        title={`Execute Playbook with Payload: ${selectedPlaybookId || ""}`}
        open={payloadModalVisible}
        onCancel={handleClosePayloadModal}
        width={700}
        footer={[
          <Button key="cancel" onClick={handleClosePayloadModal}>
            Cancel
          </Button>,
          <Button
            key="execute"
            type="primary"
            onClick={handleExecuteWithPayload}
          >
            Execute with Payload
          </Button>,
        ]}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Tabs activeKey={activePayloadTab} onChange={setActivePayloadTab}>
            <TabPane tab="JSON Input" key="json">
              <Space
                direction="vertical"
                size="small"
                style={{ width: "100%" }}
              >
                <Text>Enter JSON payload:</Text>
                <TextArea
                  rows={8}
                  placeholder='{"key": "value", "param": "example"}'
                  value={payloadJson}
                  onChange={(e) => setPayloadJson(e.target.value)}
                />
              </Space>
            </TabPane>
            <TabPane tab="File Upload" key="file">
              <Space
                direction="vertical"
                size="small"
                style={{ width: "100%" }}
              >
                <Text>Upload JSON file:</Text>
                <Upload
                  beforeUpload={handleFileUpload}
                  maxCount={1}
                  accept=".json"
                  fileList={
                    payloadFile
                      ? [{ uid: "1", name: payloadFile.name, status: "done" }]
                      : []
                  }
                  onRemove={() => setPayloadFile(null)}
                >
                  <Button icon={<UploadOutlined />}>Select JSON File</Button>
                </Upload>
                {payloadFile && (
                  <Text type="secondary">Selected: {payloadFile.name}</Text>
                )}
              </Space>
            </TabPane>
          </Tabs>

          <Checkbox
            checked={mergePayload}
            onChange={(e) => setMergePayload(e.target.checked)}
          >
            Merge with existing payload
          </Checkbox>
        </Space>
      </Modal>

      {/* Create Playbook Modal */}
      <Modal
        title="Create New Playbook"
        open={createModalVisible}
        onCancel={handleCloseCreateModal}
        width={800}
        footer={[
          <Button key="cancel" onClick={handleCloseCreateModal}>
            Cancel
          </Button>,
          <Button
            key="create"
            type="primary"
            onClick={handleCreatePlaybook}
          >
            Register Playbook
          </Button>,
        ]}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Tabs activeKey={activeCreateTab} onChange={setActiveCreateTab}>
            <TabPane tab="JSON/YAML" key="json">
              <Space
                direction="vertical"
                size="small"
                style={{ width: "100%" }}
              >
                <Text>Enter playbook definition (JSON or YAML):</Text>
                <TextArea
                  rows={18}
                  placeholder={`apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: my_playbook
  path: catalog/my_playbook
workload:
  variable: value
workflow:
  - step: start
    desc: Start workflow
    next:
      - step: end
  - step: end
    desc: End workflow`}
                  value={createPlaybookJson}
                  onChange={(e) => setCreatePlaybookJson(e.target.value)}
                  style={{ fontFamily: "monospace" }}
                />
              </Space>
            </TabPane>
            <TabPane tab="Upload File" key="file">
              <Space
                direction="vertical"
                size="small"
                style={{ width: "100%" }}
              >
                <Text>Upload playbook file (JSON or YAML):</Text>
                <Upload
                  beforeUpload={handleCreatePlaybookFileUpload}
                  maxCount={1}
                  accept=".json,.yaml,.yml"
                  fileList={
                    createPlaybookFile
                      ? [{ uid: "1", name: createPlaybookFile.name, status: "done" }]
                      : []
                  }
                  onRemove={() => setCreatePlaybookFile(null)}
                >
                  <Button icon={<UploadOutlined />}>Select Playbook File</Button>
                </Upload>
                {createPlaybookFile && (
                  <Text type="secondary">Selected: {createPlaybookFile.name}</Text>
                )}
                <Alert
                  message="Playbook Structure"
                  description={
                    <pre style={{ fontSize: "12px", margin: 0 }}>
                      {`apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: example_playbook
  path: catalog/examples/example
workload:
  param1: value1
workflow:
  - step: start
    desc: Entry point
    next:
      - step: process
  - step: process
    tool: python
    code: |
      def main(input_data):
        return {"result": "success"}
    next:
      - step: end
  - step: end
    desc: End workflow`}
                    </pre>
                  }
                  type="info"
                  style={{ marginTop: "16px" }}
                />
              </Space>
            </TabPane>
            <TabPane tab="Generate with AI" key="ai">
              <Space
                direction="vertical"
                size="small"
                style={{ width: "100%" }}
              >
                <Text>Describe the playbook you want:</Text>
                <TextArea
                  rows={6}
                  placeholder="Example: Build a playbook that fetches weather for a city, transforms it, and stores daily stats in Postgres."
                  value={createPlaybookAiPrompt}
                  onChange={(e) => setCreatePlaybookAiPrompt(e.target.value)}
                />
                <Space>
                  <Button
                    type="primary"
                    icon={<RobotOutlined />}
                    loading={generatingPlaybookAi}
                    onClick={handleGeneratePlaybookWithAI}
                  >
                    Generate Draft
                  </Button>
                  <Button
                    onClick={handleUseAIDraftInEditor}
                    disabled={!createPlaybookAiDraft.trim()}
                  >
                    Use Draft in JSON/YAML
                  </Button>
                </Space>
                {createPlaybookAiResult?.ai_execution_id && (
                  <Text type="secondary">
                    AI execution: {createPlaybookAiResult.ai_execution_id} ({createPlaybookAiResult.ai_execution_status || "unknown"})
                  </Text>
                )}
                <TextArea
                  rows={12}
                  value={createPlaybookAiDraft}
                  readOnly
                  placeholder="Generated draft will appear here."
                  style={{ fontFamily: "monospace" }}
                />
              </Space>
            </TabPane>
          </Tabs>
        </Space>
      </Modal>

      <Modal
        title={`Explain Playbook with AI${explainResult?.target_path ? `: ${explainResult.target_path}` : ""}`}
        open={explainModalVisible}
        onCancel={handleCloseExplainModal}
        width={900}
        footer={[
          <Button key="close" onClick={handleCloseExplainModal}>
            Close
          </Button>,
          <Button
            key="copy"
            icon={<FileTextOutlined />}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(JSON.stringify(explainResult?.ai_report || {}, null, 2));
                message.success("AI explanation copied");
              } catch {
                message.error("Failed to copy explanation");
              }
            }}
          >
            Copy Explanation
          </Button>,
        ]}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Text type="secondary">
            AI execution: {explainResult?.ai_execution_id || "-"} ({explainResult?.ai_execution_status || "unknown"})
          </Text>
          <TextArea
            rows={20}
            readOnly
            value={JSON.stringify(explainResult?.ai_report || {}, null, 2)}
            style={{ fontFamily: "monospace" }}
          />
        </Space>
      </Modal>
    </Content>
  );
};

export default Catalog;
