import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Spin, Alert, Typography, Button, Space, Tag, Table } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { apiService } from '../services/api';
import { ExecutionData } from '../types';
import moment from 'moment';

const { Title, Text } = Typography;

const ExecutionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [execution, setExecution] = useState<ExecutionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchExecution = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await apiService.getExecution(id!);
        setExecution(data);
      } catch (err) {
        setError('Failed to load execution details.');
      } finally {
        setLoading(false);
      }
    };
    fetchExecution();
  }, [id]);



  if (loading) {
    return <Spin style={{ display: 'block', margin: '40px auto' }} />;
  }
  if (error) {
    return <Alert message="Error" description={error} type="error" showIcon style={{ margin: 40 }} />;
  }
  if (!execution) {
    return <Alert message="Not found" description="Execution not found." type="warning" showIcon style={{ margin: 40 }} />;
  }

  const columns = [
    { title: 'Event Type', dataIndex: 'event_type', key: 'event_type' },
    { title: 'Node Name', dataIndex: 'node_name', key: 'node_name' },
    { title: 'Status', dataIndex: 'status', key: 'status', render: (status: string) => <Tag color={status === 'success' ? 'green' : 'blue'}>{status}</Tag> },
    { title: 'Timestamp', dataIndex: 'timestamp', key: 'timestamp', render: (ts: string) => moment(ts).format('YYYY-MM-DD HH:mm:ss') },
    { title: 'Duration', dataIndex: 'duration', key: 'duration', render: (d: number) => `${d}s` },
  ];

  return (
    <Card style={{ margin: 40 }}>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ marginBottom: 16 }}>
        Back
      </Button>
      <Title level={3}>Execution Details</Title>
      <Space direction="vertical" size="small">
        <Text strong>ID:</Text> <Text code>{execution.id}</Text>
        <Text strong>Playbook:</Text> <Text>{execution.playbook_name}</Text>
        <Text strong>Status:</Text> <Tag color={execution.status === 'completed' ? 'green' : execution.status === 'failed' ? 'red' : 'blue'}>{execution.status}</Tag>
        <Text strong>Start Time:</Text> <Text>{moment(execution.start_time).format('YYYY-MM-DD HH:mm:ss')}</Text>
        <Text strong>End Time:</Text> <Text>{execution.end_time ? moment(execution.end_time).format('YYYY-MM-DD HH:mm:ss') : '-'}</Text>
        <Text strong>Progress:</Text> <Text>{execution.progress}%</Text>
        <Text strong>Result:</Text> <Text code>{JSON.stringify(execution.result)}</Text>
        {execution.error && (<><Text strong>Error:</Text> <Text type="danger">{execution.error}</Text></>)}
      </Space>
      <Title level={4} style={{ marginTop: 32 }}>Events</Title>
      <Table
        dataSource={execution.events || []}
        columns={columns}
        rowKey="event_id"
        pagination={false}
        size="small"
      />
    </Card>
  );
};

export default ExecutionDetail;
