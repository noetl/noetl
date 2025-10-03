import React, { useState, useEffect, useCallback } from "react";
import {
  Layout,
  Table,
  Button,
  Typography,
  Space,
  Spin,
  Alert,
  Tag,
  Card,
  Row,
  Col,
  Progress,
  Tabs,
  Select,
  DatePicker,
  Input,
} from "antd";
import {
  PlayCircleOutlined,
  StopOutlined,
  ReloadOutlined,
  EyeOutlined,
  FilterOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { ExecutionData } from "../types";
import moment from "moment";
import { useNavigate, useLocation } from "react-router-dom";
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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../styles/Execution.css";
import FlowVisualization from "./FlowVisualization";

const { Content } = Layout;
const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;
const { RangePicker } = DatePicker;

// Node types for workflow visualization
const nodeTypes = {
  log: { color: "#52c41a", icon: "📝" },
  http: { color: "#1890ff", icon: "🌐" },
  sql: { color: "#722ed1", icon: "🗄️" },
  script: { color: "#fa8c16", icon: "⚙️" },
  secret: { color: "#eb2f96", icon: "🔑" },
  export: { color: "#13c2c2", icon: "📤" },
  python: { color: "#3776ab", icon: "🐍" },
  workbook: { color: "#ff6b35", icon: "📊" },
  default: { color: "#8c8c8c", icon: "📄" },
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
  const [filteredExecutions, setFilteredExecutions] = useState<ExecutionData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showWorkflowVisualization, setShowWorkflowVisualization] = useState(false);
  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string>('');
  const [selectedPlaybookName, setSelectedPlaybookName] = useState<string>('');

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [workflowLoading, setWorkflowLoading] = useState(false);

  // Pagination state for executions table
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);

  // Filtering state
  const [activeTab, setActiveTab] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [playbookFilter, setPlaybookFilter] = useState<string>("");
  const [searchText, setSearchText] = useState<string>("");
  const [dateRange, setDateRange] = useState<[any, any] | null>(null);

  const navigate = useNavigate();
  const location = useLocation();

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]

  );

  // React to query string changes (supports navigating between history and workflow without full remount)
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const qsPlaybook = params.get("playbook");
    const qsView = params.get("view");
    // Prefer explicit state passed via navigate if present
    const navState: any = (location as any).state || {};
    const statePlaybook = navState.playbookId;
    const stateView = navState.view;
    const playbookId = statePlaybook || qsPlaybook;
    const view = stateView || qsView;
    if (playbookId && view === "workflow") {
      if (playbookId !== selectedPlaybookId) {
        setSelectedPlaybookId(playbookId);
        setSelectedPlaybookName(playbookId);
      }
      setShowWorkflowVisualization(true);
    } else {
      setShowWorkflowVisualization(false);
    }
  }, [location, selectedPlaybookId]);

  useEffect(() => {
    fetchExecutions();

    // Set up auto-refresh for active executions
    const interval = setInterval(async () => {
      try {
        const response = await apiService.getExecutions();
        if (
          response.some(
            (exec: ExecutionData) =>
              exec.status === "running" || exec.status === "pending",
          )
        ) {
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
      setFilteredExecutions(response); // Initialize filtered executions
    } catch (err) {
      console.error("Failed to fetch executions:", err);
      setError("Failed to load execution data.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Filter executions based on current filters
  const applyFilters = useCallback(() => {
    let filtered = [...executions];

    // Filter by tab (event type)
    if (activeTab !== "all") {
      filtered = filtered.filter((exec) => exec.status === activeTab);
    }

    // Filter by status (multiple selection)
    if (statusFilter.length > 0) {
      filtered = filtered.filter((exec) => statusFilter.includes(exec.status));
    }

    // Filter by playbook name
    if (playbookFilter) {
      filtered = filtered.filter((exec) =>
        exec.playbook_name.toLowerCase().includes(playbookFilter.toLowerCase())
      );
    }

    // Filter by search text (search in playbook name and ID)
    if (searchText) {
      filtered = filtered.filter(
        (exec) =>
          exec.playbook_name.toLowerCase().includes(searchText.toLowerCase()) ||
          exec.id.toLowerCase().includes(searchText.toLowerCase()) ||
          exec.playbook_id.toLowerCase().includes(searchText.toLowerCase())
      );
    }

    // Filter by date range
    if (dateRange && dateRange[0] && dateRange[1]) {
      const [startDate, endDate] = dateRange;
      filtered = filtered.filter((exec) => {
        const execDate = new Date(exec.start_time);
        return execDate >= startDate.toDate() && execDate <= endDate.toDate();
      });
    }

    setFilteredExecutions(filtered);
  }, [executions, activeTab, statusFilter, playbookFilter, searchText, dateRange]);

  // Apply filters whenever filter criteria change
  useEffect(() => {
    applyFilters();
  }, [applyFilters]);

  // Reset to first page when filters or page size change
  useEffect(() => {
    setCurrentPage(1);
  }, [filteredExecutions.length, pageSize]);

  const clearFilters = () => {
    setActiveTab("all");
    setStatusFilter([]);
    setPlaybookFilter("");
    setSearchText("");
    setDateRange(null);
    setCurrentPage(1);
  };

  const handleStopExecution = async (executionId: string) => {
    try {
      await apiService.stopExecution(executionId);
      await fetchExecutions(true);
    } catch (err) {
      console.error("Failed to stop execution:", err);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "running":
        return "processing";
      case "completed":
        return "success";
      case "failed":
        return "error";
      case "pending":
        return "default";
      default:
        return "default";
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case "running":
        return "Running";
      case "completed":
        return "Completed";
      case "failed":
        return "Failed";
      case "pending":
        return "Pending";
      default:
        return status;
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
      console.log("🔍 PARSING PLAYBOOK CONTENT");

      const lines = content.split("\n");
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
        if (
          trimmed === "workflow:" ||
          trimmed.startsWith("workflow:") ||
          trimmed === "tasks:" ||
          trimmed.startsWith("tasks:") ||
          trimmed === "steps:" ||
          trimmed.startsWith("steps:")
        ) {
          inWorkflowSection = true;
          workflowIndent = indent;
          continue;
        }

        if (inWorkflowSection) {
          // Check if we've left the workflow section
          if (
            trimmed &&
            indent <= workflowIndent &&
            !trimmed.startsWith("-") &&
            trimmed.includes(":") &&
            !trimmed.startsWith("#")
          ) {
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
          if (
            trimmed.startsWith("- step:") &&
            !inNestedLogic &&
            indent === workflowIndent + 2
          ) {
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
            }

            const stepMatch = trimmed.match(/step:\s*([^'"]+)/);
            const taskName = stepMatch
              ? stepMatch[1].trim()
              : `Step ${taskIndex + 1}`;

            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, "_").toLowerCase(),
              name: taskName,
              type: "default",
            };
          } else if (
            trimmed.startsWith("desc:") &&
            currentTask.name &&
            !inNestedLogic
          ) {
            const descMatch = trimmed.match(
              /desc:\s*['"](.*?)['"]|desc:\s*(.+)/,
            );
            if (descMatch) {
              const description = (descMatch[1] || descMatch[2] || "")
                .trim()
                .replace(/^["']|["']$/g, "");
              currentTask.name = description;
            }
          } else if (
            trimmed.startsWith("type:") &&
            currentTask.name &&
            !inNestedLogic
          ) {
            const typeMatch = trimmed.match(
              /type:\s*['"](.*?)['"]|type:\s*([^'"]+)/,
            );
            if (typeMatch) {
              currentTask.type = (typeMatch[1] || typeMatch[2] || "").trim();
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
      console.error("💥 Error parsing playbook content:", error);
      return [];
    }
  };

  const createFlowFromTasks = (
    tasks: TaskNode[],
  ): { nodes: Node[]; edges: Edge[] } => {
    const flowNodes: Node[] = [];
    const flowEdges: Edge[] = [];

    tasks.forEach((task, index) => {
      const nodeType =
        nodeTypes[task.type as keyof typeof nodeTypes] || nodeTypes.default;

      const x = (index % 4) * 280 + 50;
      const y = Math.floor(index / 4) * 160 + 50;

      flowNodes.push({
        id: task.id,
        type: "default",
        position: { x, y },
        data: {
          label: (
            <div
              style={{
                padding: "16px 20px",
                borderRadius: "12px",
                background: "white",
                border: `2px solid ${nodeType.color}`,
                boxShadow: "0 4px 12px rgba(0, 0, 0, 0.15)",
                minWidth: "180px",
                textAlign: "center",
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              <div style={{ fontSize: "24px", marginBottom: "8px" }}>
                {nodeType.icon}
              </div>
              <div
                style={{
                  fontWeight: "bold",
                  fontSize: "14px",
                  color: "#262626",
                  marginBottom: "6px",
                  lineHeight: "1.3",
                }}
              >
                {task.name}
              </div>
              <div
                style={{
                  fontSize: "11px",
                  color: nodeType.color,
                  textTransform: "uppercase",
                  fontWeight: "600",
                  letterSpacing: "0.5px",
                }}
              >
                {task.type}
              </div>
            </div>
          ),
        },
        style: {
          background: "transparent",
          border: "none",
          padding: 0,
          width: "auto",
          height: "auto",
        },
      });
    });

    tasks.forEach((task, index) => {
      if (task.dependencies && task.dependencies.length > 0) {
        task.dependencies.forEach((dep) => {
          const sourceTask = tasks.find((t) => t.name === dep);
          if (sourceTask) {
            flowEdges.push({
              id: `edge-${sourceTask.id}-${task.id}`,
              source: sourceTask.id,
              target: task.id,
              animated: true,
              style: { stroke: '#1890ff', strokeWidth: 3, strokeDasharray: '0' }

            });
          }
        });
      } else if (index > 0) {
        flowEdges.push({
          id: `edge-${tasks[index - 1].id}-${task.id}`,
          source: tasks[index - 1].id,
          target: task.id,
          animated: true,
          style: { stroke: '#1890ff', strokeWidth: 3, strokeDasharray: '0' }
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
          const { nodes: flowNodes, edges: flowEdges } =
            createFlowFromTasks(tasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
        } else {
          // Show demo flow if no tasks found
          const demoTasks: TaskNode[] = [
            { id: "demo-1", name: "Initialize Process", type: "log" },
            { id: "demo-2", name: "Process Data", type: "script" },
            { id: "demo-3", name: "Export Results", type: "export" },
          ];
          const { nodes: flowNodes, edges: flowEdges } =
            createFlowFromTasks(demoTasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
        }
      }
    } catch (error) {
      console.error("Failed to load workflow:", error);
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
      title: "Execution ID",
      dataIndex: "id",
      key: "id",
      render: (id: string) => <Text code>{id.substring(0, 8)}</Text>,
    },
    {
      title: "Playbook",
      dataIndex: "playbook_name",
      key: "playbook_name",
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag color={getStatusColor(status)}>{getStatusText(status)}</Tag>
      ),
    },
    {
      title: "Progress",
      dataIndex: "progress",
      key: "progress",
      render: (progress: number, record: ExecutionData) => (
        <Progress
          percent={progress}
          size="small"
          status={record.status === "failed" ? "exception" : "active"}
          showInfo={false}
        />
      ),
    },
    {
      title: "Start Time",
      dataIndex: "start_time",
      key: "start_time",
      render: (startTime: string) =>
        moment(startTime).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "Duration",
      key: "duration",
      render: (record: ExecutionData) =>
        formatDuration(record.start_time, record.end_time),
    },
    {
      title: "Actions",
      key: "actions",
      render: (record: ExecutionData) => (
        <Space>
          <Button
            type="text"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/execution/${record.id}`)}
          >
            View
          </Button>
          {(record.status === "running" || record.status === "pending") && (
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

  const runningExecutions = filteredExecutions.filter(
    (exec) => exec.status === "running",
  );
  const pendingExecutions = filteredExecutions.filter(
    (exec) => exec.status === "pending",
  );
  const completedExecutions = filteredExecutions.filter(
    (exec) => exec.status === "completed",
  );
  const failedExecutions = filteredExecutions.filter(
    (exec) => exec.status === "failed",
  );

  // Get unique playbook names for filter dropdown
  const uniquePlaybooks = Array.from(
    new Set(executions.map((exec) => exec.playbook_name))
  );

  if (loading) {
    return (
      <Content className="execution-loading-content">
        <Spin size="large" />
        <div className="execution-loading-text">Loading executions...</div>
      </Content>
    );
  }

  if (error) {
    return (
      <Content className="execution-error-content">
        <Alert message="Error" description={error} type="error" showIcon />
      </Content>
    );
  }

  return (
    <Content className="execution-main-content">
      {showWorkflowVisualization ? (
        <Space direction="vertical" size="large" className="execution-space-vertical">
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
                  navigate("/execution");
                }}
              >
                Back to Executions
              </Button>
            </Col>
          </Row>

          {/* Inline Flow Visualization using shared component in read-only view mode */}
          <FlowVisualization
            visible={showWorkflowVisualization}
            embedded={showWorkflowVisualization}
            readOnly
            hideTitle
            onClose={() => {
              setShowWorkflowVisualization(false);
              navigate("/execution");
            }}
            playbookId={selectedPlaybookId}
            playbookName={selectedPlaybookName}
          />
        </Space>
      ) : (
        // Show normal execution history
        <Space direction="vertical" size="large" className="execution-space-vertical">
          <Row justify="space-between" align="middle">
            <Col>
              <Title level={2}>⚡ Execution History</Title>
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

          {/* Event Type Filtering Section */}
          <Card title={<><FilterOutlined /> Event Type Filters</>} size="small">
            <Space direction="vertical" className="execution-filter-space">
              {/* Tabs for main event types */}
              <Tabs
                activeKey={activeTab}
                onChange={setActiveTab}
                size="small"
              >
                <TabPane tab="All Events" key="all" />
                <TabPane tab={`Running (${executions.filter(e => e.status === "running").length})`} key="running" />
                <TabPane tab={`Pending (${executions.filter(e => e.status === "pending").length})`} key="pending" />
                <TabPane tab={`Completed (${executions.filter(e => e.status === "completed").length})`} key="completed" />
                <TabPane tab={`Failed (${executions.filter(e => e.status === "failed").length})`} key="failed" />
              </Tabs>

              {/* Additional Filters */}
              <Row gutter={16}>
                <Col span={6}>
                  <Input
                    placeholder="Search executions..."
                    prefix={<SearchOutlined />}
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    allowClear
                  />
                </Col>
                <Col span={6}>
                  <Select
                    mode="multiple"
                    placeholder="Filter by status"
                    className="execution-filter-select"
                    value={statusFilter}
                    onChange={setStatusFilter}
                    allowClear
                  >
                    <Option value="running">Running</Option>
                    <Option value="pending">Pending</Option>
                    <Option value="completed">Completed</Option>
                    <Option value="failed">Failed</Option>
                  </Select>
                </Col>
                <Col span={6}>
                  <Select
                    placeholder="Filter by playbook"
                    className="execution-filter-select"
                    value={playbookFilter}
                    onChange={setPlaybookFilter}
                    allowClear
                    showSearch
                  >
                    {uniquePlaybooks.map((playbook) => (
                      <Option key={playbook} value={playbook}>
                        {playbook}
                      </Option>
                    ))}
                  </Select>
                </Col>
                <Col span={4}>
                  <RangePicker
                    placeholder={["Start date", "End date"]}
                    className="execution-date-picker"
                    value={dateRange}
                    onChange={setDateRange}
                  />
                </Col>
                <Col span={2}>
                  <Button onClick={clearFilters} type="default">
                    Clear
                  </Button>
                </Col>
              </Row>
            </Space>
          </Card>

          {/* Execution Statistics */}
          <Row gutter={16}>
            <Col span={6}>
              <Card>
                <Space direction="vertical" size="small">
                  <Text type="secondary">Running</Text>
                  <Title level={3} className="execution-stats-title running">
                    {runningExecutions.length}
                  </Title>
                </Space>
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Space direction="vertical" size="small">
                  <Text type="secondary">Pending</Text>
                  <Title level={3} className="execution-stats-title pending">
                    {pendingExecutions.length}
                  </Title>
                </Space>
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Space direction="vertical" size="small">
                  <Text type="secondary">Completed</Text>
                  <Title level={3} className="execution-stats-title completed">
                    {completedExecutions.length}
                  </Title>
                </Space>
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Space direction="vertical" size="small">
                  <Text type="secondary">Failed</Text>
                  <Title level={3} className="execution-stats-title failed">
                    {failedExecutions.length}
                  </Title>
                </Space>
              </Card>
            </Col>
          </Row>

          {/* Executions Table */}
          <Table
            dataSource={filteredExecutions}
            columns={columns}
            rowKey="id"
            pagination={{
              current: currentPage,
              pageSize: pageSize,
              pageSizeOptions: ["10", "20", "50", "100"],
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total, range) =>
                `${range[0]}-${range[1]} of ${total} executions (${filteredExecutions.length} filtered from ${executions.length} total)`,
              onChange: (page) => setCurrentPage(page),
              onShowSizeChange: (_current, size) => {
                setPageSize(size);
                setCurrentPage(1);
              },
            }}
            loading={refreshing}
          />

          {filteredExecutions.length === 0 && executions.length > 0 && (
            <Alert
              message="No executions match current filters"
              description="Try adjusting your filters to see more results."
              type="info"
              showIcon
              action={
                <Button size="small" onClick={clearFilters}>
                  Clear Filters
                </Button>
              }
            />
          )}

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
