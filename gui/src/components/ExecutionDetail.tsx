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
  StopOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { apiService } from "../services/api";
import { ExecutionData, ExecutionEvent } from "../types";
import moment from "moment";
import "../styles/ExecutionDetail.css";
import { CopyOutlined, ExpandAltOutlined, CompressOutlined } from "@ant-design/icons";

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;
const { RangePicker } = DatePicker;
type AnalysisMode = "report" | "dry_run" | "apply";

// JSON stringify cache to avoid repeated heavy stringify on same object refs
const jsonStringCache = new WeakMap<object, string>();

const ExecutionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [execution, setExecution] = useState<ExecutionData | null>(null);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [filteredEvents, setFilteredEvents] = useState<ExecutionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<any | null>(null);
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("report");

  // Pagination state for events table
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(100);
  const [totalEvents, setTotalEvents] = useState<number>(0);
  const [totalPages, setTotalPages] = useState<number>(1);

  // Server-side pagination state
  const [serverPagination, setServerPagination] = useState<{
    page: number;
    page_size: number;
    total_events: number;
    total_pages: number;
    has_next: boolean;
    has_prev: boolean;
  } | null>(null);

  // Track latest event ID for incremental polling
  const [latestEventId, setLatestEventId] = useState<number | null>(null);

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
        // Initial fetch with pagination
        const data = await apiService.getExecution(id!, { page: 1, page_size: pageSize });
        setExecution(data);

        // Store pagination info
        if (data.pagination) {
          setServerPagination(data.pagination);
          setTotalEvents(data.pagination.total_events);
          setTotalPages(data.pagination.total_pages);
        }

        // Events are already sorted by server (DESC by event_id, most recent first)
        const executionEvents = data.events || [];
        setEvents(executionEvents);
        setFilteredEvents(executionEvents);

        // Track latest event ID for incremental polling
        if (executionEvents.length > 0) {
          const maxEventId = Math.max(...executionEvents.map((e: any) => e.event_id || 0));
          setLatestEventId(maxEventId);
        }
      } catch (err) {
        setError("Failed to load execution details.");
      } finally {
        setLoading(false);
      }
    };
    fetchExecution();

    // Incremental polling - only fetch new events since latestEventId
    const fetchIncrementalEvents = async () => {
      try {
        // Skip polling if execution is completed/failed/cancelled
        if (execution?.status) {
          const status = execution.status.toUpperCase();
          if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(status)) {
            return;
          }
        }

        // Fetch new events incrementally using since_event_id
        const params: any = { page_size: 50 };
        if (latestEventId) {
          params.since_event_id = latestEventId;
        }

        const data = await apiService.getExecution(id!, params);
        setError(null);
        setExecution(data);

        // Update pagination info
        if (data.pagination) {
          setServerPagination(data.pagination);
          setTotalEvents(data.pagination.total_events);
          setTotalPages(data.pagination.total_pages);
        }

        const newEvents = data.events || [];
        if (newEvents.length > 0) {
          // Prepend new events (they're most recent)
          setEvents(prev => {
            // Deduplicate by event_id
            const existingIds = new Set(prev.map((e: any) => e.event_id));
            const uniqueNew = newEvents.filter((e: any) => !existingIds.has(e.event_id));
            return [...uniqueNew, ...prev];
          });

          // Update latest event ID
          const maxEventId = Math.max(...newEvents.map((e: any) => e.event_id || 0));
          if (maxEventId > (latestEventId || 0)) {
            setLatestEventId(maxEventId);
          }
        }
      } catch (err) {
        console.warn("Failed to fetch incremental events:", err);
      }
    };

    // Adaptive polling interval - stop polling for completed executions
    const getPollingInterval = () => {
      if (!execution) return 5000;
      const status = execution.status?.toUpperCase();
      if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(status || '')) {
        return null; // Stop polling
      }
      return 5000;
    };

    const interval = setInterval(() => {
      const shouldPoll = getPollingInterval() !== null;
      if (shouldPoll) {
        fetchIncrementalEvents();
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [id, latestEventId, execution?.status, pageSize]);

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

  // Load additional events from server when user navigates pagination
  const loadServerPage = async (page: number) => {
    if (!id) return;
    try {
      const data = await apiService.getExecution(id, { page, page_size: pageSize });
      const newEvents = data.events ?? [];
      if (newEvents.length > 0) {
        // Merge with existing events, deduplicating
        setEvents(prev => {
          const existingIds = new Set(prev.map((e: any) => e.event_id));
          const uniqueNew = newEvents.filter((e: any) => !existingIds.has(e.event_id));
          const merged = [...prev, ...uniqueNew];
          // Sort by event_id DESC (most recent first)
          return merged.sort((a: any, b: any) => (b.event_id || 0) - (a.event_id || 0));
        });
      }
      if (data.pagination) {
        setServerPagination(data.pagination);
        setTotalEvents(data.pagination.total_events);
        setTotalPages(data.pagination.total_pages);
      }
    } catch (err) {
      console.error("Failed to load server page:", err);
    }
  };

  const handleCancelExecution = async () => {
    if (!id) return;

    try {
      setCancelling(true);
      await apiService.cancelExecution(id, "User requested cancellation from UI", true);
      message.success("Execution cancelled successfully");

      // Refresh execution data
      const data = await apiService.getExecution(id);
      setExecution(data);
      const executionEvents = data.events || [];
      setEvents(executionEvents);
      setFilteredEvents(executionEvents);
    } catch (err: any) {
      console.error("Failed to cancel execution:", err);
      const errorMsg = err.response?.data?.message || "Failed to cancel execution";
      message.error(errorMsg);
    } finally {
      setCancelling(false);
    }
  };

  const handleAnalyzeExecution = async (mode: AnalysisMode = "report") => {
    if (!id) return;
    try {
      setAnalyzing(true);
      setAnalysisMode(mode);
      const result = await apiService.analyzeExecutionWithAI(id, {
        max_events: 1200,
        event_sample_size: 120,
        include_playbook_content: false,
        include_event_rows: true,
        event_rows_limit: 120,
        include_event_log_rows: false,
        event_log_rows_limit: 40,
        include_patch_diff: true,
        auto_fix_mode: mode,
        approval_required: true,
        approved: mode === "apply",
        timeout_seconds: 180,
        poll_interval_ms: 1500,
      });
      setAnalysis(result);
      message.success("AI analysis generated");
    } catch (err: any) {
      console.error("Failed to analyze execution:", err);
      message.error(err?.response?.data?.detail || "Failed to generate AI execution analysis");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleCopyAnalysisPrompt = async () => {
    const prompt = analysis?.bundle?.ai_prompt || analysis?.ai_prompt;
    if (!prompt) {
      message.warning("No AI prompt available");
      return;
    }
    try {
      await navigator.clipboard.writeText(prompt);
      message.success("AI prompt copied to clipboard");
    } catch {
      message.error("Failed to copy prompt");
    }
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
      render: (d: number) => {
        if (!d || d === 0) return "-";

        // Duration is in milliseconds
        if (d < 1000) {
          return `${d.toFixed(0)}ms`;
        } else if (d < 60000) {
          // Less than 60 seconds
          return `${(d / 1000).toFixed(2)}s`;
        } else if (d < 3600000) {
          // Less than 60 minutes
          const minutes = Math.floor(d / 60000);
          const seconds = ((d % 60000) / 1000).toFixed(0);
          return `${minutes}m ${seconds}s`;
        } else {
          // 60 minutes or more
          const hours = Math.floor(d / 3600000);
          const minutes = Math.floor((d % 3600000) / 60000);
          return `${hours}h ${minutes}m`;
        }
      },
    },
  ];
  const canCancel = execution?.status?.toLowerCase() === "running" || execution?.status?.toLowerCase() === "pending";
  const analysisBundle = analysis?.bundle || analysis || {};
  const analysisSummary = analysisBundle?.summary || {};
  const analysisFindings: any[] = Array.isArray(analysisBundle?.findings) ? analysisBundle.findings : [];
  const analysisRecommendations: string[] = Array.isArray(analysisBundle?.recommendations) ? analysisBundle.recommendations : [];
  const analysisCloud = analysisBundle?.cloud || {};
  const aiReport = analysis?.ai_report || {};
  const patchDiff = typeof aiReport?.proposed_patch_diff === "string" ? aiReport.proposed_patch_diff : "";
  const dryRunCommands: string[] = Array.isArray(aiReport?.dry_run_commands) ? aiReport.dry_run_commands : [];
  const testCommands: string[] = Array.isArray(aiReport?.test_commands) ? aiReport.test_commands : [];
  const applyChecklist: string[] = Array.isArray(aiReport?.apply_checklist) ? aiReport.apply_checklist : [];

  return (
    <Card className="execution-detail-container">
      <Space className="execution-detail-header-actions">
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(-1)}
          className="execution-detail-back-button"
        >
          Back
        </Button>
        {canCancel && (
          <Button
            danger
            icon={<StopOutlined />}
            onClick={handleCancelExecution}
            loading={cancelling}
          >
            Cancel Execution
          </Button>
        )}
        <Button
          icon={<RobotOutlined />}
          onClick={() => handleAnalyzeExecution("report")}
          loading={analyzing && analysisMode === "report"}
        >
          Analyze with AI
        </Button>
        <Button
          onClick={() => handleAnalyzeExecution("dry_run")}
          loading={analyzing && analysisMode === "dry_run"}
        >
          Run Dry-Run + Tests
        </Button>
        <Button
          type="primary"
          danger
          onClick={() => handleAnalyzeExecution("apply")}
          loading={analyzing && analysisMode === "apply"}
        >
          Approve & Apply Plan
        </Button>
      </Space>

      <Title level={3}>Execution Details</Title>

      {/* Execution Info Grid */}
      <Card size="small" className="execution-detail-info-card">
        <Row gutter={[24, 16]}>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">ID</Text>
              <Text code className="execution-detail-value">{execution.execution_id}</Text>
            </div>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">Playbook</Text>
              <Text className="execution-detail-value">{execution.path}</Text>
            </div>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <div className="execution-detail-field">
              <Text className="execution-detail-label">Status</Text>
              <Tag
                color={
                  execution?.status?.toLowerCase() === "completed"
                    ? "green"
                    : execution?.status?.toLowerCase() === "failed"
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
                {execution.start_time ? moment(execution.start_time).format("YYYY-MM-DD HH:mm:ss") : "-"}
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

      {analysis && (
        <Card
          size="small"
          title="AI Triage + Fix Plan"
          className="execution-detail-info-card"
          extra={
            <Space>
              <Button size="small" icon={<CopyOutlined />} onClick={handleCopyAnalysisPrompt}>
                Copy AI Prompt
              </Button>
              {analysisCloud?.logs_url && (
                <Button
                  size="small"
                  type="link"
                  href={analysisCloud.logs_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open Cloud Logs
                </Button>
              )}
              {analysisCloud?.metrics_url && (
                <Button
                  size="small"
                  type="link"
                  href={analysisCloud.metrics_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open Metrics
                </Button>
              )}
            </Space>
          }
        >
          <Row gutter={[24, 12]}>
            <Col xs={24} md={8}>
              <Text className="execution-detail-label">Duration (sec)</Text>
              <div><Text className="execution-detail-value">{analysisSummary?.duration_seconds ?? "-"}</Text></div>
            </Col>
            <Col xs={24} md={8}>
              <Text className="execution-detail-label">Event Count</Text>
              <div><Text className="execution-detail-value">{analysisSummary?.event_count ?? "-"}</Text></div>
            </Col>
            <Col xs={24} md={8}>
              <Text className="execution-detail-label">Retry Attempts</Text>
              <div><Text className="execution-detail-value">{analysisSummary?.retry_attempts ?? 0}</Text></div>
            </Col>
            <Col xs={24} md={8}>
              <Text className="execution-detail-label">AI Execution</Text>
              <div>
                <Text className="execution-detail-value">{analysis?.ai_execution_id || "-"}</Text>
              </div>
            </Col>
            <Col xs={24} md={8}>
              <Text className="execution-detail-label">AI Status</Text>
              <div>
                <Tag color={(analysis?.ai_execution_status || "").toLowerCase() === "completed" ? "green" : (analysis?.ai_execution_status || "").toLowerCase() === "failed" ? "red" : "blue"}>
                  {analysis?.ai_execution_status || "UNKNOWN"}
                </Tag>
              </div>
            </Col>
            <Col xs={24} md={8}>
              <Text className="execution-detail-label">Mode</Text>
              <div>
                <Text className="execution-detail-value">{analysis?.auto_fix_mode || "report"}</Text>
              </div>
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">Executive Summary</Text>
              <div style={{ marginTop: 8 }}>
                <Text>{aiReport?.executive_summary || "No summary available."}</Text>
              </div>
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">Findings</Text>
              {analysisFindings.length === 0 && <div><Text>No findings</Text></div>}
              {analysisFindings.map((finding: any, idx: number) => (
                <div key={`finding-${idx}`} style={{ marginTop: 8 }}>
                  <Tag color={finding.severity === "high" ? "red" : finding.severity === "medium" ? "orange" : "blue"}>
                    {(finding.severity || "info").toUpperCase()}
                  </Tag>
                  <Text strong>{finding.title}</Text>
                  <div><Text>{finding.detail}</Text></div>
                </div>
              ))}
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">Recommendations</Text>
              {analysisRecommendations.map((item: string, idx: number) => (
                <div key={`rec-${idx}`} style={{ marginTop: 6 }}>
                  <Text>{idx + 1}. {item}</Text>
                </div>
              ))}
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">AI Prioritized Changes</Text>
              {(Array.isArray(aiReport?.recommended_dsl_runtime_changes) ? aiReport.recommended_dsl_runtime_changes : []).length === 0 && (
                <div><Text>No AI change proposals</Text></div>
              )}
              {(Array.isArray(aiReport?.recommended_dsl_runtime_changes) ? aiReport.recommended_dsl_runtime_changes : []).map((item: any, idx: number) => (
                <div key={`change-${idx}`} style={{ marginTop: 8 }}>
                  <Tag color={String(item?.priority || "").toLowerCase() === "high" ? "red" : String(item?.priority || "").toLowerCase() === "medium" ? "orange" : "blue"}>
                    {String(item?.priority || "info").toUpperCase()}
                  </Tag>
                  <Text strong>{item?.title || `Change ${idx + 1}`}</Text>
                  <div><Text>{item?.change || item?.rationale || ""}</Text></div>
                </div>
              ))}
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">Dry-Run Commands</Text>
              {dryRunCommands.length === 0 && <div><Text>-</Text></div>}
              {dryRunCommands.map((cmd: string, idx: number) => (
                <div key={`dry-${idx}`} style={{ marginTop: 6 }}>
                  <Text code>{cmd}</Text>
                </div>
              ))}
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">Test Commands</Text>
              {testCommands.length === 0 && <div><Text>-</Text></div>}
              {testCommands.map((cmd: string, idx: number) => (
                <div key={`test-${idx}`} style={{ marginTop: 6 }}>
                  <Text code>{cmd}</Text>
                </div>
              ))}
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">Apply Checklist</Text>
              {applyChecklist.length === 0 && <div><Text>-</Text></div>}
              {applyChecklist.map((item: string, idx: number) => (
                <div key={`apply-${idx}`} style={{ marginTop: 6 }}>
                  <Text>{idx + 1}. {item}</Text>
                </div>
              ))}
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">Proposed Patch Diff (AI)</Text>
              <Input.TextArea
                value={patchDiff}
                readOnly
                autoSize={{ minRows: 6, maxRows: 20 }}
                style={{ marginTop: 8, fontFamily: "monospace" }}
              />
            </Col>
            <Col xs={24}>
              <Text className="execution-detail-label">AI Prompt</Text>
              <Input.TextArea
                value={analysisBundle?.ai_prompt || ""}
                readOnly
                autoSize={{ minRows: 8, maxRows: 20 }}
                style={{ marginTop: 8, fontFamily: "monospace" }}
              />
            </Col>
          </Row>
        </Card>
      )}

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
