import React, { useState, useEffect } from 'react';
import { Layout, Table, Button, Typography, Space, Spin, Alert, Tag, Card, Row, Col, Progress } from 'antd';
import { PlayCircleOutlined, StopOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import { apiService } from '../services/api';
import { ExecutionData } from '../types';
import moment from 'moment';
import { useNavigate } from 'react-router-dom';

const { Content } = Layout;
const { Title, Text } = Typography;

const Execution: React.FC = () => {
  const [executions, setExecutions] = useState<ExecutionData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetchExecutions();

    // Set up auto-refresh for active executions
    const interval = setInterval(async () => {
      try {
        const response = await apiService.getExecutions();
        if (response.some((exec: ExecutionData) => exec.status === 'running' || exec.status === 'pending')) {
          setExecutions(response);
        }
      } catch (err) {
        // Optionally handle error
      }
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  const fetchExecutions = async (isRefresh = false) => {
    try {
      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const response = await apiService.getExecutions();
      setExecutions(response);
    } catch (err) {
      console.error('Failed to fetch executions:', err);
      setError('Failed to load execution data.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleStopExecution = async (executionId: string) => {
    try {
      await apiService.stopExecution(executionId);
      await fetchExecutions(true);
    } catch (err) {
      console.error('Failed to stop execution:', err);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'processing';
      case 'completed': return 'success';
      case 'failed': return 'error';
      case 'pending': return 'default';
      default: return 'default';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'running': return 'Running';
      case 'completed': return 'Completed';
      case 'failed': return 'Failed';
      case 'pending': return 'Pending';
      default: return status;
    }
  };

  const formatDuration = (startTime: string, endTime?: string) => {
    const start = moment(startTime);
    const end = endTime ? moment(endTime) : moment();
    const duration = moment.duration(end.diff(start));

    if (duration.asSeconds() < 60) {
      return `${Math.round(duration.asSeconds())}s`;
    } else if (duration.asMinutes() < 60) {
      return `${Math.round(duration.asMinutes())}m ${Math.round(duration.asSeconds() % 60)}s`;
    } else {
      return `${Math.round(duration.asHours())}h ${Math.round(duration.asMinutes() % 60)}m`;
    }
  };

  const columns = [
    {
      title: 'Execution ID',
      dataIndex: 'id',
      key: 'id',
      render: (id: string) => (
        <Text code>{id.substring(0, 8)}</Text>
      ),
    },
    {
      title: 'Playbook',
      dataIndex: 'playbook_name',
      key: 'playbook_name',
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>
          {getStatusText(status)}
        </Tag>
      ),
    },
    {
      title: 'Progress',
      dataIndex: 'progress',
      key: 'progress',
      render: (progress: number, record: ExecutionData) => (
        <Progress
          percent={progress}
          size="small"
          status={record.status === 'failed' ? 'exception' : 'active'}
          showInfo={false}
        />
      ),
    },
    {
      title: 'Start Time',
      dataIndex: 'start_time',
      key: 'start_time',
      render: (startTime: string) => moment(startTime).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: 'Duration',
      key: 'duration',
      render: (record: ExecutionData) => formatDuration(record.start_time, record.end_time),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (record: ExecutionData) => (
        <Space>
          <Button
            type="text"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/execution/${record.id}`)}
          >
            View
          </Button>
          {(record.status === 'running' || record.status === 'pending') && (
            <Button
              type="text"
              danger
              icon={<StopOutlined />}
              onClick={() => handleStopExecution(record.id)}
            >
              Stop
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const runningExecutions = executions.filter(exec => exec.status === 'running');
  const pendingExecutions = executions.filter(exec => exec.status === 'pending');
  const completedExecutions = executions.filter(exec => exec.status === 'completed');
  const failedExecutions = executions.filter(exec => exec.status === 'failed');

  if (loading) {
    return (
      <Content style={{ padding: '50px', textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>Loading executions...</div>
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
        <Row justify="space-between" align="middle">
          <Col>
            <Title level={2}>Execution History</Title>
          </Col>
          <Col>
            <Button
              type="default"
              icon={<ReloadOutlined />}
              loading={refreshing}
              onClick={() => fetchExecutions(true)}
            >
              Refresh
            </Button>
          </Col>
        </Row>

        {/* Execution Statistics */}
        <Row gutter={16}>
          <Col span={6}>
            <Card>
              <Space direction="vertical" size="small">
                <Text type="secondary">Running</Text>
                <Title level={3} style={{ margin: 0, color: '#1890ff' }}>
                  {runningExecutions.length}
                </Title>
              </Space>
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Space direction="vertical" size="small">
                <Text type="secondary">Pending</Text>
                <Title level={3} style={{ margin: 0, color: '#faad14' }}>
                  {pendingExecutions.length}
                </Title>
              </Space>
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Space direction="vertical" size="small">
                <Text type="secondary">Completed</Text>
                <Title level={3} style={{ margin: 0, color: '#52c41a' }}>
                  {completedExecutions.length}
                </Title>
              </Space>
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Space direction="vertical" size="small">
                <Text type="secondary">Failed</Text>
                <Title level={3} style={{ margin: 0, color: '#ff4d4f' }}>
                  {failedExecutions.length}
                </Title>
              </Space>
            </Card>
          </Col>
        </Row>

        {/* Executions Table */}
        <Table
          dataSource={executions}
          columns={columns}
          rowKey="id"
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total, range) =>
              `${range[0]}-${range[1]} of ${total} executions`,
          }}
          loading={refreshing}
        />

        {executions.length === 0 && (
          <Alert
            message="No executions found"
            description="No playbook executions have been started yet."
            type="info"
            showIcon
          />
        )}
      </Space>
    </Content>
  );
};

export default Execution;
