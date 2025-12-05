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
    Tooltip,
    Form,
    Select,
    Upload,
    Tabs,
} from "antd";
import {
    SearchOutlined,
    EyeOutlined,
    EyeInvisibleOutlined,
    CopyOutlined,
    KeyOutlined,
    EditOutlined,
    DeleteOutlined,
    PlusOutlined,
    UploadOutlined,
    ExclamationCircleOutlined,
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { CredentialData } from "../types";
import "../styles/Credentials.css";

const { Content } = Layout;
const { Title, Text } = Typography;
const { Search, TextArea } = Input;
const { TabPane } = Tabs;

const Credentials: React.FC = () => {
    const [credentials, setCredentials] = useState<CredentialData[]>([]);
    const [allCredentials, setAllCredentials] = useState<CredentialData[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchLoading, setSearchLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState("");
    const [visibleDataIds, setVisibleDataIds] = useState<Set<string>>(new Set());

    // Modal state
    const [modalVisible, setModalVisible] = useState(false);
    const [modalMode, setModalMode] = useState<"create" | "edit">("create");
    const [editingCredential, setEditingCredential] = useState<CredentialData | null>(null);
    const [form] = Form.useForm();

    // Input mode state
    const [inputMode, setInputMode] = useState<"form" | "json" | "file">("form");
    const [jsonInput, setJsonInput] = useState("");
    const [uploadFile, setUploadFile] = useState<File | null>(null);

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
        [allCredentials],
    );

    const handleSearchInternal = useCallback(
        async (query: string) => {
            if (!query.trim()) {
                // If empty search, show all credentials
                setCredentials(allCredentials);
                return;
            }

            try {
                setSearchLoading(true);

                // Try server-side search first
                try {
                    const results = await apiService.searchCredentials(query);
                    setCredentials(results);
                } catch (serverError) {
                    // Fallback to client-side search if server search fails
                    console.warn(
                        "Server search failed, falling back to client-side search:",
                        serverError,
                    );
                    const filteredCredentials = allCredentials.filter(
                        (credential) =>
                            credential.name.toLowerCase().includes(query.toLowerCase()) ||
                            credential.type.toLowerCase().includes(query.toLowerCase()) ||
                            (credential.description &&
                                credential.description
                                    .toLowerCase()
                                    .includes(query.toLowerCase())) ||
                            (credential.tags &&
                                credential.tags.some((tag) =>
                                    tag.toLowerCase().includes(query.toLowerCase())
                                ))
                    );
                    setCredentials(filteredCredentials);
                }
            } catch (err) {
                console.error("Search failed:", err);
                message.error("Search failed. Please try again.");
            } finally {
                setSearchLoading(false);
            }
        },
        [allCredentials],
    );

    const handleSearch = (query: string) => {
        handleSearchInternal(query);
    };

    useEffect(() => {
        fetchCredentials();
    }, []);

    const fetchCredentials = async () => {
        try {
            setLoading(true);
            setError(null);

            // Fetch credentials from FastAPI
            const credentialsResponse = await apiService.getCredentials();

            setCredentials(credentialsResponse);
            setAllCredentials(credentialsResponse);
        } catch (err) {
            console.error("Failed to fetch credentials:", err);
            setError(
                "Failed to load credentials. Please check if the server is running.",
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

    const toggleDataVisibility = async (credentialId: string) => {
        const newVisibleIds = new Set(visibleDataIds);

        if (newVisibleIds.has(credentialId)) {
            // Hide data
            newVisibleIds.delete(credentialId);
            setVisibleDataIds(newVisibleIds);
        } else {
            // Show data - need to fetch with include_data=true
            try {
                const credentialWithData = await apiService.getCredential(credentialId, true);

                // Update credentials array with data
                setCredentials(prevCredentials =>
                    prevCredentials.map(cred =>
                        cred.id === credentialId
                            ? { ...cred, data: credentialWithData.data }
                            : cred
                    )
                );

                newVisibleIds.add(credentialId);
                setVisibleDataIds(newVisibleIds);
            } catch (err) {
                console.error("Failed to fetch credential data:", err);
                message.error("Failed to load credential data.");
            }
        }
    };

    const handleCopyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
        message.success("Copied to clipboard");
    };

    const getTypeColor = (type: string) => {
        const typeColorMap: Record<string, string> = {
            postgres: "blue",
            snowflake: "cyan",
            http: "green",
            google_service_account: "orange",
            google_oauth: "orange",
            gcp: "orange",
            httpBearerAuth: "purple",
            generic: "default",
        };
        return typeColorMap[type] || "default";
    };

    const formatDataValue = (value: any): string => {
        if (typeof value === 'object') {
            return JSON.stringify(value, null, 2);
        }
        return String(value);
    };

    const handleCreateCredential = () => {
        setModalMode("create");
        setEditingCredential(null);
        setInputMode("form");
        setJsonInput("");
        setUploadFile(null);
        form.resetFields();
        setModalVisible(true);
    };

    const handleEditCredential = async (credential: CredentialData) => {
        setModalMode("edit");
        setEditingCredential(credential);
        setInputMode("form");

        // Fetch full credential data for editing
        try {
            const fullCredential = await apiService.getCredential(credential.id, true);
            form.setFieldsValue({
                name: fullCredential.name,
                type: fullCredential.type,
                description: fullCredential.description,
                tags: fullCredential.tags?.join(", ") || "",
                data: JSON.stringify(fullCredential.data || {}, null, 2),
            });
            setModalVisible(true);
        } catch (err) {
            console.error("Failed to fetch credential for editing:", err);
            message.error("Failed to load credential data.");
        }
    };

    const handleDeleteCredential = (credential: CredentialData) => {
        Modal.confirm({
            title: "Delete Credential",
            icon: <ExclamationCircleOutlined />,
            content: `Are you sure you want to delete credential "${credential.name}"? This action cannot be undone.`,
            okText: "Delete",
            okType: "danger",
            cancelText: "Cancel",
            onOk: async () => {
                try {
                    await apiService.deleteCredential(credential.id);
                    message.success(`Credential "${credential.name}" deleted successfully.`);
                    fetchCredentials();
                } catch (err) {
                    console.error("Failed to delete credential:", err);
                    message.error("Failed to delete credential.");
                }
            },
        });
    };

    const handleModalOk = async () => {
        try {
            let credentialData: any;

            if (inputMode === "form") {
                const values = await form.validateFields();
                credentialData = {
                    name: values.name,
                    type: values.type,
                    description: values.description,
                    tags: values.tags ? values.tags.split(",").map((t: string) => t.trim()) : [],
                    data: JSON.parse(values.data),
                };
            } else if (inputMode === "json") {
                credentialData = JSON.parse(jsonInput);
            } else if (inputMode === "file" && uploadFile) {
                const fileContent = await uploadFile.text();
                credentialData = JSON.parse(fileContent);
            } else {
                message.error("Please provide credential data.");
                return;
            }

            await apiService.createOrUpdateCredential(credentialData);
            message.success(
                `Credential "${credentialData.name}" ${modalMode === "edit" ? "updated" : "created"} successfully.`
            );
            setModalVisible(false);
            fetchCredentials();
        } catch (err: any) {
            console.error("Failed to save credential:", err);
            if (err instanceof SyntaxError) {
                message.error("Invalid JSON format. Please check your input.");
            } else {
                message.error(err.message || "Failed to save credential.");
            }
        }
    };

    const handleModalCancel = () => {
        setModalVisible(false);
        setEditingCredential(null);
        form.resetFields();
        setJsonInput("");
        setUploadFile(null);
    };

    const handleFileUpload = (file: File) => {
        setUploadFile(file);
        return false; // Prevent auto upload
    };

    const handleJsonInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setJsonInput(e.target.value);
    };

    const getExampleJson = (type: string) => {
        const examples: Record<string, any> = {
            postgres: {
                name: "my_postgres",
                type: "postgres",
                description: "PostgreSQL database",
                tags: ["database", "postgres"],
                data: {
                    db_host: "localhost",
                    db_port: "5432",
                    db_user: "username",
                    db_password: "password",
                    db_name: "database_name",
                },
            },
            snowflake: {
                name: "my_snowflake",
                type: "snowflake",
                description: "Snowflake with RSA key-pair auth",
                tags: ["snowflake", "keypair"],
                data: {
                    sf_account: "ACCOUNT-LOCATOR",
                    sf_user: "USERNAME",
                    sf_private_key: "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
                    sf_warehouse: "WAREHOUSE_NAME",
                    sf_database: "DATABASE_NAME",
                    sf_schema: "SCHEMA_NAME",
                    sf_role: "ROLE_NAME",
                },
            },
            google_service_account: {
                name: "my_gcp_sa",
                type: "google_service_account",
                description: "GCP service account",
                tags: ["gcp", "service-account"],
                data: {
                    type: "service_account",
                    project_id: "project-id",
                    private_key_id: "key-id",
                    private_key: "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
                    client_email: "service-account@project.iam.gserviceaccount.com",
                    client_id: "client-id",
                },
            },
            httpBearerAuth: {
                name: "my_bearer_token",
                type: "httpBearerAuth",
                description: "HTTP Bearer token",
                tags: ["http", "token"],
                data: {
                    token: "your-bearer-token-here",
                },
            },
        };
        return examples[type] || examples.postgres;
    };

    if (loading) {
        return (
            <Content className="credentials-loading-content">
                <Spin size="large" />
                <div className="credentials-loading-text">Loading credentials...</div>
            </Content>
        );
    }

    if (error) {
        return (
            <Content className="credentials-error-content">
                <Alert message="Error" description={error} type="error" showIcon />
            </Content>
        );
    }

    return (
        <Content className="credentials-main-content">
            <Space direction="vertical" size="large" className="credentials-space-vertical">
                <div className="credentials-header">
                    <Title level={2}>🔐 Credentials</Title>
                    <Button
                        type="primary"
                        icon={<PlusOutlined />}
                        onClick={handleCreateCredential}
                    >
                        New Credential
                    </Button>
                </div>

                <Search
                    placeholder="Search credentials by name, type, description, or tags..."
                    allowClear
                    enterButton={<SearchOutlined />}
                    size="large"
                    loading={searchLoading}
                    value={searchQuery}
                    onSearch={handleSearch}
                    onChange={handleSearchInputChange}
                />

                {/* Credentials list */}
                <Space direction="vertical" size="middle" className="credentials-credentials-space">
                    {credentials.map((credential) => (
                        <Card key={credential.id} size="small" className="credentials-credential-card">
                            <div className="credentials-card-container">
                                <Row gutter={16}>
                                    <Col flex="auto">
                                        <Space
                                            direction="horizontal"
                                            size="large"
                                            className="credentials-credential-row"
                                        >
                                            <div className="credentials-card-content">
                                                <Title level={5} className="credentials-card-header">
                                                    <KeyOutlined className="credentials-card-icon" />
                                                    {credential.name}
                                                    <Tag
                                                        color={getTypeColor(credential.type)}
                                                        className="credentials-card-type-tag"
                                                    >
                                                        {credential.type}
                                                    </Tag>
                                                </Title>
                                                <Space direction="horizontal" size="large">
                                                    <Text type="secondary">ID: {credential.id}</Text>
                                                    <Text type="secondary">
                                                        Created: {new Date(credential.created_at).toLocaleDateString()}
                                                    </Text>
                                                    <Text type="secondary">
                                                        Updated: {new Date(credential.updated_at).toLocaleDateString()}
                                                    </Text>
                                                </Space>
                                                {credential.description && (
                                                    <div className="credentials-card-meta">
                                                        <Text type="secondary">{credential.description}</Text>
                                                    </div>
                                                )}
                                                {credential.tags && credential.tags.length > 0 && (
                                                    <div className="credentials-card-tags">
                                                        {credential.tags.map((tag) => (
                                                            <Tag key={tag} className="credentials-card-tag">
                                                                {tag}
                                                            </Tag>
                                                        ))}
                                                    </div>
                                                )}

                                                {/* Show credential data if visible */}
                                                {visibleDataIds.has(credential.id) && credential.data && (
                                                    <Card
                                                        size="small"
                                                        className="credentials-data-card"
                                                    >
                                                        <Space direction="vertical" size="small" className="credentials-data-container">
                                                            <Text strong>Credential Data:</Text>
                                                            {Object.entries(credential.data).map(([key, value]) => (
                                                                <div key={key} className="credentials-data-item">
                                                                    <Text type="secondary">{key}: </Text>
                                                                    <Text
                                                                        code
                                                                        copyable={{
                                                                            text: formatDataValue(value),
                                                                            tooltips: ["Copy", "Copied!"],
                                                                        }}
                                                                    >
                                                                        {key.toLowerCase().includes("password") ||
                                                                            key.toLowerCase().includes("secret") ||
                                                                            key.toLowerCase().includes("token")
                                                                            ? "••••••••"
                                                                            : formatDataValue(value)}
                                                                    </Text>
                                                                </div>
                                                            ))}
                                                        </Space>
                                                    </Card>
                                                )}
                                            </div>
                                        </Space>
                                    </Col>
                                </Row>
                                <div className="credentials-actions">
                                    <Space>
                                        <Button
                                            type="text"
                                            icon={
                                                visibleDataIds.has(credential.id) ? (
                                                    <EyeInvisibleOutlined />
                                                ) : (
                                                    <EyeOutlined />
                                                )
                                            }
                                            onClick={() => toggleDataVisibility(credential.id)}
                                        >
                                            {visibleDataIds.has(credential.id) ? "Hide" : "View"}
                                        </Button>
                                        <Button
                                            type="text"
                                            icon={<CopyOutlined />}
                                            onClick={() => handleCopyToClipboard(credential.id)}
                                        >
                                            Copy
                                        </Button>
                                        <Button
                                            type="text"
                                            icon={<EditOutlined />}
                                            onClick={() => handleEditCredential(credential)}
                                        >
                                            Edit
                                        </Button>
                                        <Button
                                            type="primary"
                                            danger
                                            icon={<DeleteOutlined />}
                                            onClick={() => handleDeleteCredential(credential)}
                                        >
                                            Delete
                                        </Button>
                                    </Space>
                                </div>
                            </div>
                        </Card>
                    ))}
                </Space>

                {credentials.length === 0 && !loading && (
                    <Alert
                        message={
                            searchQuery ? "No credentials found" : "No credentials available"
                        }
                        description={
                            searchQuery
                                ? `No credentials match your search for "${searchQuery}".`
                                : "There are no credentials stored yet."
                        }
                        type="info"
                        showIcon
                    />
                )}
            </Space>

            {/* Credential Create/Edit Modal */}
            <Modal
                title={modalMode === "create" ? "Create Credential" : "Edit Credential"}
                open={modalVisible}
                onOk={handleModalOk}
                onCancel={handleModalCancel}
                width={800}
                okText={modalMode === "create" ? "Create" : "Update"}
            >
                <Tabs activeKey={inputMode} onChange={(key) => setInputMode(key as any)}>
                    <TabPane tab="Form" key="form">
                        <Form form={form} layout="vertical">
                            <Form.Item
                                name="name"
                                label="Name"
                                rules={[{ required: true, message: "Please enter credential name" }]}
                            >
                                <Input placeholder="my_credential" />
                            </Form.Item>

                            <Form.Item
                                name="type"
                                label="Type"
                                rules={[{ required: true, message: "Please select credential type" }]}
                            >
                                <Select
                                    placeholder="Select credential type"
                                    onChange={(value) => {
                                        const example = getExampleJson(value);
                                        form.setFieldsValue({
                                            data: JSON.stringify(example.data, null, 2),
                                        });
                                    }}
                                >
                                    <Select.Option value="postgres">PostgreSQL</Select.Option>
                                    <Select.Option value="snowflake">Snowflake</Select.Option>
                                    <Select.Option value="google_service_account">Google Service Account</Select.Option>
                                    <Select.Option value="google_oauth">Google OAuth</Select.Option>
                                    <Select.Option value="httpBearerAuth">HTTP Bearer Auth</Select.Option>
                                    <Select.Option value="http">HTTP</Select.Option>
                                    <Select.Option value="generic">Generic</Select.Option>
                                </Select>
                            </Form.Item>

                            <Form.Item name="description" label="Description">
                                <Input placeholder="Optional description" />
                            </Form.Item>

                            <Form.Item name="tags" label="Tags">
                                <Input placeholder="comma, separated, tags" />
                            </Form.Item>

                            <Form.Item
                                name="data"
                                label="Credential Data (JSON)"
                                rules={[
                                    { required: true, message: "Please enter credential data" },
                                    {
                                        validator: (_, value) => {
                                            try {
                                                if (value) JSON.parse(value);
                                                return Promise.resolve();
                                            } catch {
                                                return Promise.reject("Invalid JSON format");
                                            }
                                        },
                                    },
                                ]}
                            >
                                <TextArea
                                    rows={10}
                                    placeholder='{ "key": "value" }'
                                    className="credentials-json-input"
                                />
                            </Form.Item>
                        </Form>
                    </TabPane>

                    <TabPane tab="JSON" key="json">
                        <Space direction="vertical" className="credentials-upload-file" size="middle">
                            <Text>Paste complete credential JSON:</Text>
                            <TextArea
                                rows={18}
                                value={jsonInput}
                                onChange={handleJsonInputChange}
                                placeholder={JSON.stringify(getExampleJson("postgres"), null, 2)}
                                className="credentials-json-input"
                            />
                        </Space>
                    </TabPane>

                    <TabPane tab="Upload File" key="file">
                        <Space direction="vertical" className="credentials-upload-file" size="middle">
                            <Text>Upload credential JSON file:</Text>
                            <Upload
                                beforeUpload={handleFileUpload}
                                maxCount={1}
                                accept=".json"
                                fileList={uploadFile ? [{ uid: "1", name: uploadFile.name, status: "done" }] : []}
                                onRemove={() => setUploadFile(null)}
                            >
                                <Button icon={<UploadOutlined />}>Select JSON File</Button>
                            </Upload>
                            {uploadFile && (
                                <Alert
                                    message={`Selected: ${uploadFile.name}`}
                                    type="info"
                                    showIcon
                                />
                            )}
                            <Alert
                                message="Example Formats"
                                description={
                                    <div>
                                        <Text strong>Snowflake (RSA Key-Pair):</Text>
                                        <pre className="credentials-example-pre">
                                            {JSON.stringify(getExampleJson("snowflake"), null, 2)}
                                        </pre>
                                        <Text strong>PostgreSQL:</Text>
                                        <pre className="credentials-example-pre">
                                            {JSON.stringify(getExampleJson("postgres"), null, 2)}
                                        </pre>
                                    </div>
                                }
                                type="info"
                                className="credentials-example-section"
                            />
                        </Space>
                    </TabPane>
                </Tabs>
            </Modal>
        </Content>
    );
};

export default Credentials;
