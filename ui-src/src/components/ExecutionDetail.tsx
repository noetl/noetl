import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Card,
  Spin,
  Alert,
  Typography,
  Button,
  Space,
  Tag,
  Table,
  Tabs,
  Select,
  Input,
  Row,
  Col,
  DatePicker
} from "antd";
import {
  ArrowLeftOutlined,
  FilterOutlined,
  SearchOutlined
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { ExecutionData } from "../types";
import moment from "moment";
import "../styles/ExecutionDetail.css";

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;
const { RangePicker } = DatePicker;

const ExecutionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [execution, setExecution] = useState<ExecutionData | null>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [filteredEvents, setFilteredEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Event filtering state
  const [activeTab, setActiveTab] = useState<string>("all");
  const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [nodeFilter, setNodeFilter] = useState<string>("");
  const [searchText, setSearchText] = useState<string>("");
  const [dateRange, setDateRange] = useState<[any, any] | null>(null);

  useEffect(() => {
    const fetchExecution = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await apiService.getExecution(id!);
        setExecution(data);

        // Extract events from execution data or create demo events if not available
        const executionEvents = (data as any).events || [
          { event_id: 1, event_type: "START", node_name: "workflow_start", status: "success", timestamp: data.start_time, duration: 0.1 },
          { event_id: 2, event_type: "TASK", node_name: "task_1", status: "success", timestamp: data.start_time, duration: 2.5 },
          { event_id: 3, event_type: "LOG", node_name: "task_1", status: "info", timestamp: data.start_time, duration: 0.1 },
          { event_id: 4, event_type: "HTTP", node_name: "api_call", status: "success", timestamp: data.start_time, duration: 1.2 },
          { event_id: 5, event_type: "ERROR", node_name: "task_2", status: "failed", timestamp: data.start_time, duration: 0.5 },
          { event_id: 6, event_type: "RETRY", node_name: "task_2", status: "success", timestamp: data.start_time, duration: 1.8 },
          { event_id: 7, event_type: "COMPLETE", node_name: "workflow_end", status: "success", timestamp: data.end_time || data.start_time, duration: 0.1 },
        ];

        setEvents(executionEvents);
        setFilteredEvents(executionEvents);
      } catch (err) {
        setError("Failed to load execution details.");
      } finally {
        setLoading(false);
      }
    };
    fetchExecution();
  }, [id]);

  // Filter events based on current filters
  const applyEventFilters = useCallback(() => {
    let filtered = [...events];

    // Filter by tab (main event types)
    if (activeTab !== "all") {
      filtered = filtered.filter((event) => event.event_type.toLowerCase() === activeTab.toLowerCase());
    }

    // Filter by event types (multiple selection)
    if (eventTypeFilter.length > 0) {
      filtered = filtered.filter((event) => eventTypeFilter.includes(event.event_type));
    }

    // Filter by status (multiple selection)
    if (statusFilter.length > 0) {
      filtered = filtered.filter((event) => statusFilter.includes(event.status));
    }

    // Filter by node name
    if (nodeFilter) {
      filtered = filtered.filter((event) =>
        event.node_name.toLowerCase().includes(nodeFilter.toLowerCase())
      );
    }

    // Filter by search text
    if (searchText) {
      filtered = filtered.filter(
        (event) =>
          event.event_type.toLowerCase().includes(searchText.toLowerCase()) ||
          event.node_name.toLowerCase().includes(searchText.toLowerCase()) ||
          event.status.toLowerCase().includes(searchText.toLowerCase())
      );
    }

    // Filter by date range
    if (dateRange && dateRange[0] && dateRange[1]) {
      const [startDate, endDate] = dateRange;
      filtered = filtered.filter((event) => {
        const eventDate = new Date(event.timestamp);
        return eventDate >= startDate.toDate() && eventDate <= endDate.toDate();
      });
    }

    setFilteredEvents(filtered);
  }, [events, activeTab, eventTypeFilter, statusFilter, nodeFilter, searchText, dateRange]);

  // Apply filters whenever filter criteria change
  useEffect(() => {
    applyEventFilters();
  }, [applyEventFilters]);

  const clearEventFilters = () => {
    setActiveTab("all");
    setEventTypeFilter([]);
    setStatusFilter([]);
    setNodeFilter("");
    setSearchText("");
    setDateRange(null);
  };

  // Get unique values for filter dropdowns
  const uniqueEventTypes = Array.from(new Set(events.map((event) => event.event_type)));
  const uniqueStatuses = Array.from(new Set(events.map((event) => event.status)));
  const uniqueNodes = Array.from(new Set(events.map((event) => event.node_name)));

  if (loading) {
    return <Spin className="execution-detail-loading" />;
  }
  if (error) {
    return (
      <Alert
        message="Error"
        description={error}
        type="error"
        showIcon
        className="execution-detail-error"
      />
    );
  }
  if (!execution) {
    return (
      <Alert
        message="Not found"
        description="Execution not found."
        type="warning"
        showIcon
        className="execution-detail-not-found"
      />
    );
  }

  const columns = [
    { title: "Event Type", dataIndex: "event_type", key: "event_type" },
    { title: "Node Name", dataIndex: "node_name", key: "node_name" },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag color={status === "success" ? "green" : "red"}>{status}</Tag>
      ),
    },
    {
      title: "Timestamp",
      dataIndex: "timestamp",
      key: "timestamp",
      render: (ts: string) => moment(ts).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "Duration",
      dataIndex: "duration",
      key: "duration",
      render: (d: number) => `${d}s`,
    },
  ];

  return (
    <Card className="execution-detail-container">
      <Button
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(-1)}
        className="execution-detail-back-button"
      >
        Back
      </Button>
      <Title level={3}>Execution Details</Title>
      <Space direction="vertical" size="small">
        <Text strong>ID:</Text> <Text code>{execution.id}</Text>
        <Text strong>Playbook:</Text> <Text>{execution.playbook_name}</Text>
        <Text strong>Status:</Text>{" "}
        <Tag
          color={
            execution.status === "completed"
              ? "green"
              : execution.status === "failed"
                ? "red"
                : "blue"
          }
        >
          {execution.status}
        </Tag>
        <Text strong>Start Time:</Text>{" "}
        <Text>
          {moment(execution.start_time).format("YYYY-MM-DD HH:mm:ss")}
        </Text>
        <Text strong>End Time:</Text>{" "}
        <Text>
          {execution.end_time
            ? moment(execution.end_time).format("YYYY-MM-DD HH:mm:ss")
            : "-"}
        </Text>
        <Text strong>Progress:</Text> <Text>{execution.progress}%</Text>
        <Text strong>Result:</Text>{" "}
        <Text code>{JSON.stringify(execution.result)}</Text>
        {execution.error && (
          <>
            <Text strong>Error:</Text>{" "}
            <Text type="danger">{execution.error}</Text>
          </>
        )}
      </Space>
      <Title level={4} className="execution-detail-events-title">
        Events
      </Title>

      {/* Event Type Filtering Section */}
      <Card title={<><FilterOutlined /> Event Type Filters</>} size="small" className="execution-detail-filter-card">
        <Space direction="vertical" className="execution-detail-filter-space">
          {/* Tabs for main event types */}
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            size="small"
          >
            <TabPane tab="All Events" key="all" />
            <TabPane tab={`Start (${events.filter(e => e.event_type === "START").length})`} key="start" />
            <TabPane tab={`Tasks (${events.filter(e => e.event_type === "TASK").length})`} key="task" />
            <TabPane tab={`HTTP (${events.filter(e => e.event_type === "HTTP").length})`} key="http" />
            <TabPane tab={`Logs (${events.filter(e => e.event_type === "LOG").length})`} key="log" />
            <TabPane tab={`Errors (${events.filter(e => e.event_type === "ERROR").length})`} key="error" />
            <TabPane tab={`Complete (${events.filter(e => e.event_type === "COMPLETE").length})`} key="complete" />
          </Tabs>

          {/* Additional Filters */}
          <Row gutter={16}>
            <Col span={6}>
              <Input
                placeholder="Search events..."
                prefix={<SearchOutlined />}
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                allowClear
              />
            </Col>
            <Col span={5}>
              <Select
                mode="multiple"
                placeholder="Filter by event type"
                className="execution-detail-event-type-select"
                value={eventTypeFilter}
                onChange={setEventTypeFilter}
                allowClear
              >
                {uniqueEventTypes.map((type) => (
                  <Option key={type} value={type}>
                    {type}
                  </Option>
                ))}
              </Select>
            </Col>
            <Col span={4}>
              <Select
                mode="multiple"
                placeholder="Filter by status"
                className="execution-detail-status-select"
                value={statusFilter}
                onChange={setStatusFilter}
                allowClear
              >
                {uniqueStatuses.map((status) => (
                  <Option key={status} value={status}>
                    {status}
                  </Option>
                ))}
              </Select>
            </Col>
            <Col span={4}>
              <Select
                placeholder="Filter by node"
                className="execution-detail-node-select"
                value={nodeFilter}
                onChange={setNodeFilter}
                allowClear
                showSearch
              >
                {uniqueNodes.map((node) => (
                  <Option key={node} value={node}>
                    {node}
                  </Option>
                ))}
              </Select>
            </Col>
            <Col span={3}>
              <RangePicker
                placeholder={["Start", "End"]}
                className="execution-detail-date-picker"
                value={dateRange}
                onChange={setDateRange}
                size="small"
              />
            </Col>
            <Col span={2}>
              <Button onClick={clearEventFilters} type="default" size="small">
                Clear
              </Button>
            </Col>
          </Row>
        </Space>
      </Card>

      <Table
        dataSource={filteredEvents}
        columns={columns}
        rowKey="event_id"
        pagination={{
          pageSize: 10,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (total, range) =>
            `${range[0]}-${range[1]} of ${total} events (${filteredEvents.length} filtered from ${events.length} total)`,
        }}
        size="small"
      />

      {filteredEvents.length === 0 && events.length > 0 && (
        <Alert
          message="No events match current filters"
          description="Try adjusting your filters to see more results."
          type="info"
          showIcon
          action={
            <Button size="small" onClick={clearEventFilters}>
              Clear Filters
            </Button>
          }
          className="execution-detail-no-filtered-events"
        />
      )}

      {events.length === 0 && (
        <Alert
          message="No events found"
          description="No events have been recorded for this execution yet."
          type="info"
          showIcon
          className="execution-detail-no-events"
        />
      )}
    </Card>
  );
};

export default ExecutionDetail;
