import React, { useState, useEffect } from 'react';
import { Layout, Row, Col, Spin, Alert, Typography, Space } from 'antd';
import { apiService } from '../services/api';
import { DashboardStats, VisualizationWidget, ServerStatus } from '../types';
import WidgetRenderer from './WidgetRenderer';

const { Content } = Layout;
const { Title } = Typography;

const Dashboard: React.FC = () => {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [widgets, setWidgets] = useState<VisualizationWidget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch server status
        const healthResponse = await apiService.getHealth();
        setStatus(healthResponse);

        // Fetch dashboard stats
        const statsResponse = await apiService.getDashboardStats();
        setStats(statsResponse);

        // Fetch visualization widgets from FastAPI
        const widgetsResponse = await apiService.getDashboardWidgets();
        setWidgets(widgetsResponse);

      } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
        setError('Failed to load dashboard data. Please check if the server is running.');
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, []);

  const renderStatus = () => {
    if (!status) return null;

    const alertType = status.status === 'healthy' ? 'success' : 'error';
    return (
      <Alert
        message={`Server Status: ${status.status}`}
        description={status.message}
        type={alertType}
        showIcon
        style={{ marginBottom: 24 }}
      />
    );
  };

  if (loading) {
    return (
      <Content style={{ padding: '50px', textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>Loading dashboard...</div>
      </Content>
    );
  }

  if (error) {
    return (
      <Content style={{ padding: '50px' }}>
        <Alert
          message="Error"
          description={error}
          type="error"
          showIcon
        />
      </Content>
    );
  }

  return (
    <Content>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Title level={2}>NoETL Dashboard</Title>

        {renderStatus()}

        {/* Render widgets from FastAPI in a responsive grid */}
        <Row gutter={[16, 16]}>
          {widgets.map((widget) => (
            <Col
              key={widget.id}
              xs={24}
              sm={12}
              md={8}
              lg={6}
              xl={6}
            >
              <WidgetRenderer widget={widget} />
            </Col>
          ))}
        </Row>

        {/* Fallback content if no widgets */}
        {widgets.length === 0 && (
          <Alert
            message="No widgets available"
            description="The FastAPI backend hasn't provided any visualization widgets yet."
            type="info"
            showIcon
          />
        )}
      </Space>
    </Content>
  );
};

export default Dashboard;
