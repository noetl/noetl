import React, { useState, useEffect } from 'react';
import { Layout, Row, Col, Input, Card, Button, Typography, Space, Spin, Alert, Tag } from 'antd';
import { SearchOutlined, PlayCircleOutlined, EditOutlined, EyeOutlined } from '@ant-design/icons';
import { apiService } from '../services/api';
import { PlaybookData, VisualizationWidget } from '../types';
import WidgetRenderer from './WidgetRenderer';

const { Content } = Layout;
const { Title, Text } = Typography;
const { Search } = Input;

const Catalog: React.FC = () => {
  const [playbooks, setPlaybooks] = useState<PlaybookData[]>([]);
  const [widgets, setWidgets] = useState<VisualizationWidget[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    fetchCatalogData();
  }, []);

  const fetchCatalogData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch playbooks and catalog widgets from FastAPI
      const [playbooksResponse, widgetsResponse] = await Promise.all([
        apiService.getPlaybooks(),
        apiService.getCatalogWidgets()
      ]);

      setPlaybooks(playbooksResponse);
      setWidgets(widgetsResponse);
    } catch (err) {
      console.error('Failed to fetch catalog data:', err);
      setError('Failed to load catalog data.');
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async (query: string) => {
    if (!query.trim()) {
      fetchCatalogData();
      return;
    }

    try {
      setSearchLoading(true);
      const results = await apiService.searchPlaybooks(query);
      setPlaybooks(results);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setSearchLoading(false);
    }
  };

  const handleExecutePlaybook = async (playbookId: string) => {
    try {
      await apiService.executePlaybook(playbookId);
      // Redirect to execution page or show success message
      window.location.href = '/execution';
    } catch (err) {
      console.error('Failed to execute playbook:', err);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'green';
      case 'inactive': return 'red';
      case 'draft': return 'orange';
      default: return 'default';
    }
  };

  if (loading) {
    return (
      <Content style={{ padding: '50px', textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>Loading catalog...</div>
      </Content>
    );
  }

  if (error) {
    return (
      <Content style={{ padding: '50px' }}>
        <Alert message="Error" description={error} type="error" showIcon />
      </Content>
    );
  }

  return (
    <Content>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Title level={2}>Playbook Catalog</Title>

        <Search
          placeholder="Search playbooks..."
          allowClear
          enterButton={<SearchOutlined />}
          size="large"
          loading={searchLoading}
          onSearch={handleSearch}
          onChange={(e) => setSearchQuery(e.target.value)}
        />

        {/* Render catalog widgets from FastAPI */}
        {widgets.length > 0 && (
          <Row gutter={[16, 16]}>
            {widgets.map((widget) => (
              <Col key={widget.id} xs={24} sm={12} md={8} lg={6}>
                <WidgetRenderer widget={widget} />
              </Col>
            ))}
          </Row>
        )}

        {/* Playbooks grid */}
        <Row gutter={[16, 16]}>
          {playbooks.map((playbook) => (
            <Col key={playbook.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                title={playbook.name}
                extra={<Tag color={getStatusColor(playbook.status)}>{playbook.status}</Tag>}
                actions={[
                  <Button
                    key="view"
                    type="text"
                    icon={<EyeOutlined />}
                    onClick={() => console.log('View playbook', playbook.id)}
                  >
                    View
                  </Button>,
                  <Button
                    key="edit"
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => window.location.href = `/editor?id=${playbook.id}`}
                  >
                    Edit
                  </Button>,
                  <Button
                    key="execute"
                    type="text"
                    icon={<PlayCircleOutlined />}
                    onClick={() => handleExecutePlaybook(playbook.id)}
                    disabled={playbook.status !== 'active'}
                  >
                    Execute
                  </Button>
                ]}
              >
                <Space direction="vertical" size="small">
                  <Text type="secondary">{playbook.description || 'No description'}</Text>
                  <Text type="secondary">Tasks: {playbook.tasks_count}</Text>
                  <Text type="secondary">
                    Updated: {new Date(playbook.updated_at).toLocaleDateString()}
                  </Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>

        {playbooks.length === 0 && (
          <Alert
            message="No playbooks found"
            description="No playbooks match your search criteria."
            type="info"
            showIcon
          />
        )}
      </Space>
    </Content>
  );
};

export default Catalog;
