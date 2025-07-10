    /**
     * @fileoverview The main entry point for the NoETL Dashboard React application.
     *
     * This file initializes the main dashboard component, which provides a status
     * overview and quick navigation links to other parts of the application.
     * It's written using modern React (with JSX) and Ant Design components.
     */

    import React, { useState, useEffect } from 'react';
    import ReactDOM from 'react-dom/client';
    import { Button, Card, Typography, Space, Layout, Spin, Alert, Grid } from 'antd';
    // Import the icons you need
    import { BookOutlined, PlusCircleOutlined, HistoryOutlined, HomeOutlined } from '@ant-design/icons';
    import 'antd/dist/reset.css';
    import '../static/css/main.css';

    const { Title, Paragraph } = Typography;
    const { Header, Content } = Layout;
    const { useBreakpoint } = Grid;

    /**
     * The main dashboard component for the NoETL application.
     */
    function NoETLDashboard() {
        // State for the server health check
        const [status, setStatus] = useState({ state: 'loading', message: 'Checking server status...' });
        const screens = useBreakpoint(); // Hook to get screen size for responsive layout

        useEffect(() => {
            // Fetch server health on component mount
            fetch('/health')
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`Server responded with status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    // Use the more descriptive message from the backend if available
                    const message = data.message || 'Connected';
                    setStatus({ state: 'success', message: message });
                })
                .catch(error => {
                    console.error('Health check failed:', error);
                    setStatus({ state: 'error', message: 'Connection failed. The backend may be down.' });
                });
        }, []); // The empty dependency array ensures this runs only once

        const renderStatus = () => {
            switch (status.state) {
                case 'loading':
                    return <Space><Spin size="small" /> <Paragraph style={{ marginBottom: 0 }}>{status.message}</Paragraph></Space>;
                case 'success':
                    return <Alert message={status.message} type="success" showIcon />;
                case 'error':
                    return <Alert message={status.message} type="error" showIcon />;
                default:
                    return null;
            }
        };

        // Determine if the layout should be vertical based on screen size
        const isVertical = !screens.md;

        return (
            <Layout style={{ minHeight: '100vh' }}>
                <Header className="app-header">
                    <div className="logo">
                        <a href="/">
                            {/* Use Ant Design Icon */}
                            <HomeOutlined />
                            <span>NoETL Dashboard</span>
                        </a>
                    </div>
                </Header>
                <Content className="app-content">
                    <div className="page-title-container">
                        <Title level={2} className="page-title">Welcome to NoETL</Title>
                        <Paragraph className="page-subtitle">
                            The "Not Only ETL" framework for building and running data pipelines.
                        </Paragraph>
                    </div>

                    <Space direction="vertical" size="large" style={{ width: '100%' }}>
                        <Card title="System Status" className="styled-card">
                            {renderStatus()}
                        </Card>

                        <Card title="Quick Actions" className="styled-card">
                            <Space direction={isVertical ? 'vertical' : 'horizontal'} size="middle" align={isVertical ? 'start' : 'center'} wrap>
                                <Button type="primary" size="large" href="/catalog" icon={<BookOutlined />}>
                                    View Playbook Catalog
                                </Button>
                                <Button size="large" href="/editor/new" icon={<PlusCircleOutlined />}>
                                    Create New Playbook
                                </Button>
                                <Button size="large" disabled icon={<HistoryOutlined />}>
                                    View Execution Logs
                                </Button>
                            </Space>
                        </Card>
                    </Space>
                </Content>
            </Layout>
        );
    }

    // --- Application Entry Point ---

    const container = document.getElementById('root');
    if (container) {
        const root = ReactDOM.createRoot(container);
        root.render(
            <React.StrictMode>
                <NoETLDashboard />
            </React.StrictMode>
        );
    } else {
        console.error('Fatal Error: Root element with id "root" not found in the DOM.');
    }
