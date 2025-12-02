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
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { CredentialData } from "../types";
import "../styles/Credentials.css";

const { Content } = Layout;
const { Title, Text } = Typography;
const { Search } = Input;

const Credentials: React.FC = () => {
    const [credentials, setCredentials] = useState<CredentialData[]>([]);
    const [allCredentials, setAllCredentials] = useState<CredentialData[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchLoading, setSearchLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState("");
    const [visibleDataIds, setVisibleDataIds] = useState<Set<string>>(new Set());

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
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <Title level={2}>🔐 Credentials</Title>
                    <Button
                        type="primary"
                        icon={<PlusOutlined />}
                        onClick={() => message.info("Create credential feature coming soon")}
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
                            <Row align="middle" gutter={16}>
                                <Col flex="auto">
                                    <Space
                                        direction="horizontal"
                                        size="large"
                                        className="credentials-credential-row"
                                    >
                                        <div style={{ width: "100%" }}>
                                            <Title level={5} style={{ margin: 0, marginBottom: 4 }}>
                                                <KeyOutlined style={{ marginRight: 8 }} />
                                                {credential.name}
                                                <Tag
                                                    color={getTypeColor(credential.type)}
                                                    style={{ marginLeft: 8 }}
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
                                                <div style={{ marginTop: 4 }}>
                                                    <Text type="secondary">{credential.description}</Text>
                                                </div>
                                            )}
                                            {credential.tags && credential.tags.length > 0 && (
                                                <div style={{ marginTop: 8 }}>
                                                    {credential.tags.map((tag) => (
                                                        <Tag key={tag} style={{ marginBottom: 4 }}>
                                                            {tag}
                                                        </Tag>
                                                    ))}
                                                </div>
                                            )}

                                            {/* Show credential data if visible */}
                                            {visibleDataIds.has(credential.id) && credential.data && (
                                                <Card
                                                    size="small"
                                                    style={{
                                                        marginTop: 12,
                                                        backgroundColor: "#f5f5f5",
                                                    }}
                                                >
                                                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                                        <Text strong>Credential Data:</Text>
                                                        {Object.entries(credential.data).map(([key, value]) => (
                                                            <div key={key} style={{ marginLeft: 12 }}>
                                                                <Text type="secondary">{key}: </Text>
                                                                <Text
                                                                    code
                                                                    copyable={{
                                                                        text: formatDataValue(value),
                                                                        tooltips: ["Copy", "Copied!"],
                                                                    }}
                                                                    style={{
                                                                        backgroundColor: "#fff",
                                                                        padding: "2px 8px",
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
                                <Col>
                                    <Space>
                                        <Tooltip title={visibleDataIds.has(credential.id) ? "Hide data" : "View data"}>
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
                                            />
                                        </Tooltip>
                                        <Tooltip title="Copy credential ID">
                                            <Button
                                                type="text"
                                                icon={<CopyOutlined />}
                                                onClick={() => handleCopyToClipboard(credential.id)}
                                            />
                                        </Tooltip>
                                        <Button
                                            type="text"
                                            icon={<EditOutlined />}
                                            onClick={() => message.info("Edit feature coming soon")}
                                        >
                                            Edit
                                        </Button>
                                        <Button
                                            type="text"
                                            danger
                                            icon={<DeleteOutlined />}
                                            onClick={() => message.info("Delete feature coming soon")}
                                        >
                                            Delete
                                        </Button>
                                    </Space>
                                </Col>
                            </Row>
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
        </Content>
    );
};

export default Credentials;
