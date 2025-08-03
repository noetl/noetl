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

    // Handle different status values - check for 'ok' or 'healthy'
    const isHealthy = status.status === 'ok' || status.status === 'healthy';
    const alertType = isHealthy ? 'info' : 'error'; // Use 'info' for blue color when status is ok
    const statusText = status.status === 'ok' ? 'Online' : status.status;
    
    return (
      <Alert
        message={`Server Status: ${statusText}`}
        description={status.message || 'NoETL server is running properly'}
        type={alertType}
        showIcon
        style={{ 
          marginBottom: 24,
          borderRadius: 8,
          ...(isHealthy && {
            backgroundColor: '#e6f7ff',
            borderColor: '#1890ff'
          })
        }}
      />
    );
  };

  if (loading) {
    return (
      <Content style={{ 
        display: 'flex', 
        flexDirection: 'column',
        alignItems: 'center', 
        justifyContent: 'center',
        minHeight: '400px',
        textAlign: 'center' 
      }}>
        <Spin size="large" />
        <div style={{ 
          marginTop: 16, 
          fontSize: '16px',
          color: '#8c8c8c',
          fontWeight: 500
        }}>
          Loading dashboard...
        </div>
      </Content>
    );
  }

  if (error) {
    return (
      <Content style={{ padding: 0 }}>
        <div style={{ 
          textAlign: 'center', 
          padding: '60px 24px',
          background: '#fff2f0',
          borderRadius: 12,
          border: '1px solid #ffccc7'
        }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
          <Title level={4} style={{ color: '#cf1322', marginBottom: 8 }}>
            Connection Error
          </Title>
          <p style={{ color: '#8c8c8c', marginBottom: 0 }}>
            {error}
          </p>
        </div>
      </Content>
    );
  }

  return (
    <Content style={{ padding: 0 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: 8
        }}>
          <Title level={2} style={{ margin: 0, color: '#262626' }}>
            📊 NoETL Dashboard
          </Title>
          <div style={{ 
            fontSize: '14px', 
            color: '#8c8c8c',
            fontWeight: 500
          }}>
            {new Date().toLocaleDateString('en-US', { 
              weekday: 'long', 
              year: 'numeric', 
              month: 'long', 
              day: 'numeric' 
            })}
          </div>
        </div>

        {renderStatus()}

        {/* Render widgets from FastAPI in a responsive grid */}
        {widgets.length > 0 && (
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
                <div style={{ 
                  background: '#fff',
                  borderRadius: 8,
                  padding: 16,
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
                  border: '1px solid #f0f0f0'
                }}>
                  <WidgetRenderer widget={widget} />
                </div>
              </Col>
            ))}
          </Row>
        )}

        {/* Enhanced fallback content if no widgets */}
        {widgets.length === 0 && (
          <div style={{ 
            textAlign: 'center', 
            padding: '60px 24px',
            background: '#fafafa',
            borderRadius: 12,
            border: '2px dashed #d9d9d9'
          }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>📈</div>
            <Title level={4} style={{ color: '#8c8c8c', marginBottom: 8 }}>
              No Widgets Available
            </Title>
            <p style={{ color: '#8c8c8c', marginBottom: 0 }}>
              The FastAPI backend hasn't provided any visualization widgets yet.
              <br />
              Check your server configuration or create some widgets to get started.
            </p>
          </div>
        )}
      </Space>
    </Content>
  );
};

export default Dashboard;
