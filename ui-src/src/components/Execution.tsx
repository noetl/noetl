import React, { useState, useEffect, useCallback } from 'react';
import { Layout, Table, Button, Typography, Space, Spin, Alert, Tag, Card, Row, Col, Progress } from 'antd';
import { PlayCircleOutlined, StopOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import { apiService } from '../services/api';
import { ExecutionData } from '../types';
import moment from 'moment';
import { useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  Node,
  Edge,
  Connection,
  BackgroundVariant,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

const { Content } = Layout;
const { Title, Text } = Typography;

// Node types for workflow visualization
const nodeTypes = {
  log: { color: '#52c41a', icon: '📝' },
  http: { color: '#1890ff', icon: '🌐' },
  sql: { color: '#722ed1', icon: '🗄️' },
  script: { color: '#fa8c16', icon: '⚙️' },
  secret: { color: '#eb2f96', icon: '🔑' },
  export: { color: '#13c2c2', icon: '📤' },
  python: { color: '#3776ab', icon: '🐍' },
  workbook: { color: '#ff6b35', icon: '📊' },
  default: { color: '#8c8c8c', icon: '📄' }
};

interface TaskNode {
  id: string;
  name: string;
  type: string;
  config?: any;
  dependencies?: string[];
}

const Execution: React.FC = () => {
  const [executions, setExecutions] = useState<ExecutionData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showWorkflowVisualization, setShowWorkflowVisualization] = useState(false);
  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string>('');
  const [selectedPlaybookName, setSelectedPlaybookName] = useState<string>('');
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const navigate = useNavigate();

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds: Edge[]) => addEdge(params, eds)),
    [setEdges]
  );

  // Check URL parameters for workflow visualization
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const playbookId = urlParams.get('playbook');
    const view = urlParams.get('view');
    
    if (playbookId && view === 'workflow') {
      setSelectedPlaybookId(playbookId);
      setSelectedPlaybookName(playbookId); // We'll use the ID as name for now
      setShowWorkflowVisualization(true);
    }
  }, []);

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

  const parsePlaybookContent = (content: string): TaskNode[] => {
    try {
      console.log('🔍 PARSING PLAYBOOK CONTENT');
      
      const lines = content.split('\n');
      const tasks: TaskNode[] = [];
      let currentTask: Partial<TaskNode> = {};
      let inWorkflowSection = false;
      let taskIndex = 0;
      let workflowIndent = 0;
      let inNestedLogic = false;
      let nestedLevel = 0;

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();
        const indent = line.length - line.trimStart().length;
        
        // Look for workflow/tasks/steps section
        if (trimmed === 'workflow:' || trimmed.startsWith('workflow:') ||
            trimmed === 'tasks:' || trimmed.startsWith('tasks:') || 
            trimmed === 'steps:' || trimmed.startsWith('steps:')) {
          inWorkflowSection = true;
          workflowIndent = indent;
          continue;
        }

        if (inWorkflowSection) {
          // Check if we've left the workflow section
          if (trimmed && indent <= workflowIndent && !trimmed.startsWith('-') && trimmed.includes(':') && !trimmed.startsWith('#')) {
            break;
          }
          
          // Detect nested logic sections
          if (trimmed.match(/^(next|then|else|when):/)) {
            if (!inNestedLogic) {
              inNestedLogic = true;
              nestedLevel = indent;
            }
            continue;
          }
          
          // Process main workflow steps
          if (trimmed.startsWith('- step:') && !inNestedLogic && indent === workflowIndent + 2) {
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
            }
            
            const stepMatch = trimmed.match(/step:\s*([^'"]+)/);
            const taskName = stepMatch ? stepMatch[1].trim() : `Step ${taskIndex + 1}`;
            
            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase(),
              name: taskName,
              type: 'default'
            };
            
          } else if (trimmed.startsWith('desc:') && currentTask.name && !inNestedLogic) {
            const descMatch = trimmed.match(/desc:\s*['"](.*?)['"]|desc:\s*(.+)/);
            if (descMatch) {
              const description = (descMatch[1] || descMatch[2] || '').trim().replace(/^["']|["']$/g, '');
              currentTask.name = description;
            }
            
          } else if (trimmed.startsWith('type:') && currentTask.name && !inNestedLogic) {
            const typeMatch = trimmed.match(/type:\s*['"](.*?)['"]|type:\s*([^'"]+)/);
            if (typeMatch) {
              currentTask.type = (typeMatch[1] || typeMatch[2] || '').trim();
            }
          }
          
          if (inNestedLogic && indent <= nestedLevel) {
            inNestedLogic = false;
          }
        }
      }

      if (currentTask.name) {
        tasks.push(currentTask as TaskNode);
      }

      return tasks;
    } catch (error) {
      console.error('💥 Error parsing playbook content:', error);
      return [];
    }
  };

  const createFlowFromTasks = (tasks: TaskNode[]): { nodes: Node[], edges: Edge[] } => {
    const flowNodes: Node[] = [];
    const flowEdges: Edge[] = [];
    
    tasks.forEach((task, index) => {
      const nodeType = nodeTypes[task.type as keyof typeof nodeTypes] || nodeTypes.default;
      
      const x = (index % 4) * 280 + 50;
      const y = Math.floor(index / 4) * 160 + 50;
      
      flowNodes.push({
        id: task.id,
        type: 'default',
        position: { x, y },
        data: {
          label: (
            <div style={{ 
              padding: '16px 20px',
              borderRadius: '12px',
              background: 'white',
              border: `2px solid ${nodeType.color}`,
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
              minWidth: '180px',
              textAlign: 'center',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}>
              <div style={{ fontSize: '24px', marginBottom: '8px' }}>
                {nodeType.icon}
              </div>
              <div style={{ 
                fontWeight: 'bold', 
                fontSize: '14px',
                color: '#262626',
                marginBottom: '6px',
                lineHeight: '1.3'
              }}>
                {task.name}
              </div>
              <div style={{ 
                fontSize: '11px', 
                color: nodeType.color,
                textTransform: 'uppercase',
                fontWeight: '600',
                letterSpacing: '0.5px'
              }}>
                {task.type}
              </div>
            </div>
          )
        },
        style: {
          background: 'transparent',
          border: 'none',
          padding: 0,
          width: 'auto',
          height: 'auto'
        }
      });
    });

    tasks.forEach((task, index) => {
      if (task.dependencies && task.dependencies.length > 0) {
        task.dependencies.forEach(dep => {
          const sourceTask = tasks.find(t => t.name === dep);
          if (sourceTask) {
            flowEdges.push({
              id: `edge-${sourceTask.id}-${task.id}`,
              source: sourceTask.id,
              target: task.id,
              animated: true,
              style: { stroke: '#1890ff', strokeWidth: 3 }
            });
          }
        });
      } else if (index > 0) {
        flowEdges.push({
          id: `edge-${tasks[index - 1].id}-${task.id}`,
          source: tasks[index - 1].id,
          target: task.id,
          animated: true,
          style: { stroke: '#1890ff', strokeWidth: 3 }
        });
      }
    });

    return { nodes: flowNodes, edges: flowEdges };
  };

  const loadWorkflowVisualization = async () => {
    if (!selectedPlaybookId) return;
    
    setWorkflowLoading(true);
    try {
      const content = await apiService.getPlaybookContent(selectedPlaybookId);
      if (content && content.trim()) {
        const tasks = parsePlaybookContent(content);
        if (tasks.length > 0) {
          const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(tasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
        } else {
          // Show demo flow if no tasks found
          const demoTasks: TaskNode[] = [
            { id: 'demo-1', name: 'Initialize Process', type: 'log' },
            { id: 'demo-2', name: 'Process Data', type: 'script' },
            { id: 'demo-3', name: 'Export Results', type: 'export' }
          ];
          const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(demoTasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
        }
      }
    } catch (error) {
      console.error('Failed to load workflow:', error);
    } finally {
      setWorkflowLoading(false);
    }
  };

  useEffect(() => {
    if (showWorkflowVisualization && selectedPlaybookId) {
      loadWorkflowVisualization();
    }
  }, [showWorkflowVisualization, selectedPlaybookId]);

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
      {showWorkflowVisualization ? (
        // Show workflow visualization when accessed via View button
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Row justify="space-between" align="middle">
            <Col>
              <Title level={2}>
                🔄 Workflow Visualization - {selectedPlaybookName}
              </Title>
            </Col>
            <Col>
              <Button
                type="default"
                onClick={() => {
                  setShowWorkflowVisualization(false);
                  navigate('/execution');
                }}
              >
                Back to Executions
              </Button>
            </Col>
          </Row>
          
          {/* Inline Flow Visualization */}
          <div style={{ height: '80vh', border: '1px solid #d9d9d9', borderRadius: '8px', padding: '20px' }}>
            {workflowLoading ? (
              <div style={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                height: '100%',
                flexDirection: 'column',
                gap: '16px'
              }}>
                <Spin size="large" />
                <div style={{ color: '#8c8c8c' }}>Loading workflow visualization...</div>
              </div>
            ) : (
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                fitView
                fitViewOptions={{ padding: 0.3 }}
                attributionPosition="bottom-left"
              >
                <Controls 
                  style={{
                    background: 'white',
                    border: '1px solid #d9d9d9',
                    borderRadius: '8px'
                  }}
                />
                <MiniMap 
                  nodeColor={(node) => '#1890ff'}
                  style={{
                    background: 'white',
                    border: '1px solid #d9d9d9',
                    borderRadius: '8px'
                  }}
                />
                <Background 
                  variant={BackgroundVariant.Dots} 
                  gap={20} 
                  size={1}
                  color="#f0f0f0"
                />
              </ReactFlow>
            )}
          </div>
        </Space>
      ) : (
        // Show normal execution history
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Title level={2}>
              ⚡ Execution History
            </Title>
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
      )}
    </Content>
  );
};

export default Execution;
