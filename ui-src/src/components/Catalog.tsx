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
  const [payloadJson, setPayloadJson] = useState("");
  const [payloadFile, setPayloadFile] = useState<File | null>(null);
  const [mergePayload, setMergePayload] = useState(false);
  const [activePayloadTab, setActivePayloadTab] = useState("json");

  // Create playbook modal state
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [createPlaybookJson, setCreatePlaybookJson] = useState("");
  const [createPlaybookFile, setCreatePlaybookFile] = useState<File | null>(null);
  const [activeCreateTab, setActiveCreateTab] = useState("json");

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
      // console.log("Playbook execution started: ", executePlaybookResponse);
      message.success("Playbook execution started successfully!");
      // Redirect to execution page
      const execution_id = executePlaybookResponse.execution_id;
      navigate(`/execution/${execution_id}`);
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

  const handleViewPayload = (playbookId: string, version: string) => {
    setSelectedPlaybookId(playbookId);
    setSelectedPlaybookVersion(version);
    setPayloadModalVisible(true);
    // Reset form
    setPayloadJson("");
    setPayloadFile(null);
    setMergePayload(false);
    setActivePayloadTab("json");
  };

  const handleExecuteWithPayload = async () => {
    if (!selectedPlaybookId || !selectedPlaybookVersion) {
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
      path: selectedPlaybookId,
      version: selectedPlaybookVersion,
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
  };

  const handleCloseCreateModal = () => {
    setCreateModalVisible(false);
    setCreatePlaybookJson("");
    setCreatePlaybookFile(null);
    setActiveCreateTab("json");
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

  const handleViewFlow = (playbookPath: string, playbookName: string) => {
    // Navigate to execution page with playbook visualization (query + state)
    navigate(`/execution?playbook=${encodeURIComponent(playbookPath)}&view=workflow`, {
      state: { playbookId: playbookPath, view: 'workflow' }
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
                      onClick={() => handleViewFlow(playbook.path, playbook.path)}
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
                        )
                      }
                    >
                      Payload
                    </Button>
                    <Button
                      type="primary"
                      icon={<PlayCircleOutlined />}
                      onClick={() => handleExecutePlaybook(playbook.catalog_id)}
                      disabled={playbook.status !== "active"}
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
          </Tabs>
        </Space>
      </Modal>
    </Content>
  );
};

export default Catalog;
