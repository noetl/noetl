import React, { useEffect, useState, useCallback, useMemo } from "react";
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
  DatePicker,
  Progress,
  message,
  Tooltip
} from "antd";
import {
  ArrowLeftOutlined,
  FilterOutlined,
  SearchOutlined,
  RightOutlined,
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { ExecutionData } from "../types";
import moment from "moment";
import "../styles/ExecutionDetail.css";
import { CopyOutlined, ExpandAltOutlined, CompressOutlined } from "@ant-design/icons";

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;
const { RangePicker } = DatePicker;

// JSON stringify cache to avoid repeated heavy stringify on same object refs
const jsonStringCache = new WeakMap<object, string>();

const ExecutionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [execution, setExecution] = useState<ExecutionData | null>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [filteredEvents, setFilteredEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination state for events table
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);

  // Event filtering state
  const [activeTab, setActiveTab] = useState<string>("all");
  const [eventTypeFilter, setEventTypeFilter] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [nodeFilter, setNodeFilter] = useState<string>("");
  const [searchText, setSearchText] = useState<string>("");
  const [dateRange, setDateRange] = useState<[any, any] | null>(null);
  // Debounced search state
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Expanded fields state for JSON rendering
  const [expandedFields, setExpandedFields] = useState<Set<string>>(new Set());

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

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(searchText), 250);
    return () => clearTimeout(handle);
  }, [searchText]);

  // Filter events based on current filters (optimized single pass)
  const applyEventFilters = useCallback(() => {
    if (!events || events.length === 0) {
      setFilteredEvents([]);
      return;
    }

    const hasTabFilter = activeTab !== "all";
    const wantsEventTypes = eventTypeFilter.length > 0;
    const wantsStatuses = statusFilter.length > 0;
    const wantsNode = !!nodeFilter;
    const wantsSearch = !!debouncedSearch;
    const wantsDateRange = !!(dateRange && dateRange[0] && dateRange[1]);

    // Precompute for O(1) membership
    const eventTypeSet = wantsEventTypes ? new Set(eventTypeFilter) : null;
    const statusSet = wantsStatuses ? new Set(statusFilter) : null;
    const loweredNode = wantsNode ? nodeFilter.toLowerCase() : null;
    const loweredSearch = wantsSearch ? debouncedSearch.toLowerCase() : null;
    const startMs = wantsDateRange ? dateRange![0].toDate().getTime() : 0;
    const endMs = wantsDateRange ? dateRange![1].toDate().getTime() : 0;
    const loweredActiveTab = hasTabFilter ? activeTab.toLowerCase() : null;

    const results: any[] = [];
    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      const etLower = e.event_type?.toLowerCase() || "";
      // Tab filter
      if (loweredActiveTab && etLower !== loweredActiveTab) continue;
      // Event type multi-select
      if (eventTypeSet && !eventTypeSet.has(e.event_type)) continue;
      // Status multi-select
      if (statusSet && !statusSet.has(e.status)) continue;
      // Node filter
      if (loweredNode && !e.node_name?.toLowerCase().includes(loweredNode)) continue;
      // Date range filter
      if (wantsDateRange) {
        const ts = new Date(e.timestamp).getTime();
        if (ts < startMs || ts > endMs) continue;
      }
      // Search text (checks several fields lowercased once each)
      if (loweredSearch) {
        const nn = e.node_name?.toLowerCase() || "";
        const st = e.status?.toLowerCase() || "";
        if (!(etLower.includes(loweredSearch) || nn.includes(loweredSearch) || st.includes(loweredSearch))) continue;
      }
      results.push(e);
    }

    setFilteredEvents(results);
  }, [events, activeTab, eventTypeFilter, statusFilter, nodeFilter, debouncedSearch, dateRange]);

  // Apply filters whenever filter criteria change
  useEffect(() => {
    applyEventFilters();
  }, [applyEventFilters]);

  // Reset to first page whenever the filtered events change
  useEffect(() => {
    setCurrentPage(1);
  }, [filteredEvents.length, pageSize]);

  const clearEventFilters = () => {
    setActiveTab("all");
    setEventTypeFilter([]);
    setStatusFilter([]);
    setNodeFilter("");
    setSearchText("");
    setDateRange(null);
  };

  // Helper to pick the first existing key from possible aliases
  const pickField = (obj: any, keys: string[]) => {
    for (const k of keys) {
      if (obj && Object.prototype.hasOwnProperty.call(obj, k) && obj[k] !== undefined && obj[k] !== null) {
        return obj[k];
      }
    }
    return undefined;
  };

  const toggleField = (id: string) => {
    setExpandedFields(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const renderJSON = (value: any) => {
    if (value === undefined || value === null) return "-";
    try {
      if (typeof value === "string") return value;
      if (typeof value === "object") {
        const cached = jsonStringCache.get(value);
        if (cached) return cached;
        const str = JSON.stringify(value, null, 2);
        jsonStringCache.set(value, str);
        return str;
      }
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  };

  const renderJSONExpandable = (record: any, fieldKey: string, value: any) => {
    const key = `${record.event_id}:${fieldKey}`;
    const str = renderJSON(value);
    const isLong = str && str.length > 100;
    const expanded = expandedFields.has(key);
    if (!isLong) return <pre className="execution-detail-pre">{str}</pre>;
    const preview = expanded ? str : str.substring(0, 100) + "...";
    const handleCopy = () => {
      navigator.clipboard.writeText(str);
      message.success("Copied to clipboard");
    };
    return (
      <div className="execution-detail-json-wrapper">
        <pre className={`execution-detail-pre ${expanded ? "expanded" : "collapsed"}`}>{preview}</pre>
        <div className="execution-detail-json-actions">
          <Tooltip title={expanded ? "Collapse" : "Expand"}>
            <Button
              type="text"
              size="small"
              icon={expanded ? <CompressOutlined /> : <ExpandAltOutlined />}
              onClick={() => toggleField(key)}
              className="execution-detail-json-btn"
            />
          </Tooltip>
          <Tooltip title="Copy full JSON">
            <Button
              type="text"
              size="small"
              icon={<CopyOutlined />}
              onClick={handleCopy}
              className="execution-detail-json-btn"
            />
          </Tooltip>
        </div>
      </div>
    );
  };

  // Get unique values for filter dropdowns (memoized)
  const uniqueEventTypes: string[] = useMemo(() => Array.from(new Set(events.map((event: any) => event.event_type))), [events]);
  const uniqueStatuses: string[] = useMemo(() => Array.from(new Set(events.map((event: any) => event.status))), [events]);
  const uniqueNodes: string[] = useMemo(() => Array.from(new Set(events.map((event: any) => event.node_name))), [events]);
  const tabCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of events) {
      counts[e.event_type] = (counts[e.event_type] || 0) + 1;
    }
    return counts;
  }, [events]);

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
        <Tag color={status.toLowerCase() === "completed"
          ? "green"
          : status.toLowerCase() === "failed"
            ? "red"
            : "blue"}>{status}</Tag>
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

      {/* Execution Info Grid */}
      <Card size="small" className="execution-detail-info-card">
        <Row gutter={[24, 16]}>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">ID</Text>
              <Text code className="execution-detail-value">{execution.id}</Text>
            </div>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">Playbook</Text>
              <Text className="execution-detail-value">{execution.playbook_name}</Text>
            </div>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">Status</Text>
              <Tag
                color={
                  execution.status.toLowerCase() === "completed"
                    ? "green"
                    : execution.status.toLowerCase() === "failed"
                      ? "red"
                      : "blue"
                }
                className="execution-detail-value"
              >
                {execution.status}
              </Tag>
            </div>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">Start Time</Text>
              <Text className="execution-detail-value">
                {moment(execution.start_time).format("YYYY-MM-DD HH:mm:ss")}
              </Text>
            </div>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">End Time</Text>
              <Text className="execution-detail-value">
                {execution.end_time
                  ? moment(execution.end_time).format("YYYY-MM-DD HH:mm:ss")
                  : "-"}
              </Text>
            </div>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">Progress</Text>
              <Progress
                percent={execution.progress}
                size="small"
                className="execution-detail-progress"
                status={execution.status === "failed" ? "exception" : "active"}
              />
            </div>
          </Col>
          {execution.result && execution.result !== null && (
            <Col xs={24}>
              <div className="execution-detail-field">
                <Text className="execution-detail-label">Result</Text>
                <Text code className="execution-detail-value execution-detail-result">
                  {JSON.stringify(execution.result)}
                </Text>
              </div>
            </Col>
          )}
          {execution.error && (
            <Col xs={24}>
              <div className="execution-detail-field">
                <Text className="execution-detail-label">Error</Text>
                <Text type="danger" className="execution-detail-value">
                  {execution.error}
                </Text>
              </div>
            </Col>
          )}
        </Row>
      </Card>

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
            <TabPane tab={`Start (${tabCounts.START || 0})`} key="start" />
            <TabPane tab={`Tasks (${tabCounts.TASK || 0})`} key="task" />
            <TabPane tab={`HTTP (${tabCounts.HTTP || 0})`} key="http" />
            <TabPane tab={`Logs (${tabCounts.LOG || 0})`} key="log" />
            <TabPane tab={`Errors (${tabCounts.ERROR || 0})`} key="error" />
            <TabPane tab={`Complete (${tabCounts.COMPLETE || 0})`} key="complete" />
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
                {uniqueEventTypes.map((type: string) => (
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
                {uniqueStatuses.map((status: string) => (
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
                {uniqueNodes.map((node: string) => (
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
          current: currentPage,
          pageSize: pageSize,
          pageSizeOptions: ["10", "20", "50", "100"],
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (total, range) =>
            `${range[0]}-${range[1]} of ${total} events (${filteredEvents.length} filtered from ${events.length} total)`,
          onChange: (page) => setCurrentPage(page),
          onShowSizeChange: (_current, size) => {
            setPageSize(size);
            setCurrentPage(1);
          },
        }}
        expandable={{
          expandIconColumnIndex: columns.length,
          columnWidth: 44,
          expandRowByClick: true,
          expandIcon: ({ expanded, onExpand, record }) => (
            <span
              className={`execution-detail-expand-icon ${expanded ? "expanded" : ""}`}
              onClick={(e) => onExpand(record, e)}
              role="button"
              aria-label={expanded ? "Collapse" : "Expand"}
            >
              <RightOutlined />
            </span>
          ),
          expandedRowRender: (record: any) => (
            <div className="execution-detail-expanded">
              <Row gutter={[24, 12]}>
                <Col xs={24} md={12}>
                  <div className="execution-detail-field">
                    <Text className="execution-detail-label">Node Name</Text>
                    <Text className="execution-detail-value">{record.node_name || "-"}</Text>
                  </div>
                </Col>
                <Col xs={24} md={12}>
                  <div className="execution-detail-field">
                    <Text className="execution-detail-label">Context Value</Text>
                    <div className="execution-detail-value execution-detail-result">
                      {renderJSONExpandable(record, "context", pickField(record, ["context", "context_value", "contextValue", "input_context"]))}
                    </div>
                  </div>
                </Col>
                <Col xs={24} md={12}>
                  <div className="execution-detail-field">
                    <Text className="execution-detail-label">Input Result</Text>
                    <div className="execution-detail-value execution-detail-result">
                      {renderJSONExpandable(record, "input", pickField(record, ["input_result", "input", "inputData", "input_context"]))}
                    </div>
                  </div>
                </Col>
                <Col xs={24} md={12}>
                  <div className="execution-detail-field">
                    <Text className="execution-detail-label">Output Result</Text>
                    <div className="execution-detail-value execution-detail-result">
                      {renderJSONExpandable(record, "output", pickField(record, ["output_result", "output", "outputData", "result"]))}
                    </div>
                  </div>
                </Col>
                <Col xs={24}>
                  <div className="execution-detail-field">
                    <Text className="execution-detail-label">Metadata</Text>
                    <div className="execution-detail-value execution-detail-result">
                      {renderJSONExpandable(record, "metadata", pickField(record, ["metadata", "meta"]))}
                    </div>
                  </div>
                </Col>
                <Col xs={24}>
                  <div className="execution-detail-field">
                    <Text className="execution-detail-label">Error</Text>
                    <div className="execution-detail-value execution-detail-result">
                      {renderJSONExpandable(record, "error", pickField(record, ["error", "message", "error_message"]))}
                    </div>
                  </div>
                </Col>
                {record.normalized_status && (
                  <Col xs={24} md={12}>
                    <div className="execution-detail-field">
                      <Text className="execution-detail-label">Normalized Status</Text>
                      <Text className="execution-detail-value">{record.normalized_status}</Text>
                    </div>
                  </Col>
                )}
              </Row>
            </div>
          ),
          rowExpandable: () => true,
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
