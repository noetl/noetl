// Common types used across the application

import Execution from "../components/Execution";

export interface ServerStatus {
  status: "ok" | "healthy" | "error" | "warning" | string;
  message: string;
  timestamp: string;
}

// export interface PlaybookData {
//   id: string;
//   name: string;
//   kind: string;
//   version: number;
//   meta: any;
//   timestamp: string;
//   status: "active" | "inactive" | "draft";
//   tasks_count: number;
//   updated_at: string;
//   description?: string;
//   created_at?: string;
// }
export interface PlaybookData {
  catalog_id: string
  path: string
  version: string
  kind?: string
  content?: string
  layout?: any
  payload?: any
  status: "active" | "inactive" | "draft";
  meta?: any
  created_at?: string
}

export interface CredentialData {
  id: string;
  name: string;
  type: string;
  meta?: any;
  tags?: string[];
  description?: string;
  created_at: string;
  updated_at: string;
  data?: Record<string, any>;
}

export interface ExecutionEvent {
  event_id: string;
  event_type: string;
  node_name: string;
  status: string;
  timestamp: string;
  duration: number;
}
export interface ExecutionData {
  execution_id: string;
  path: string;
  version: string;
  status: "running" | "completed" | "failed" | "pending";
  start_time: string;
  end_time?: string;
  duration?: number;
  progress: number;
  result?: any;
  error?: string;
  events?: Array<ExecutionEvent>;
}

export interface DashboardStats {
  total_playbooks: number;
  total_executions: number;
  active_executions: number;
  success_rate: number;
  recent_executions: ExecutionData[];
}

export interface MenuItemType {
  key: string;
  label: string;
  icon: React.ReactNode;
  path: string;
}

export interface AppContextType {
  serverStatus: ServerStatus | null;
  isLoading: boolean;
  error: string | null;
}

export interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
  error?: string;
}

export interface TableColumn {
  key: string;
  title: string;
  dataIndex: string;
  render?: (value: any, record: any) => React.ReactNode;
  sorter?: boolean;
  filterable?: boolean;
  width?: number;
}

export interface ChartConfig {
  type: "line" | "bar" | "pie" | "area" | "scatter";
  xAxis?: string;
  yAxis?: string;
  series?: string[];
  colors?: string[];
  title?: string;
  subtitle?: string;
  legend?: boolean;
  grid?: boolean;
  responsive?: boolean;
}

// Visualization widget definition used by WidgetRenderer
export interface VisualizationWidget {
  id: string;
  type: 'metric' | 'progress' | 'table' | 'list' | 'text' | 'chart';
  title: string;
  // Data payload varies by widget type; keep flexible with typed common fields
  data: {
    value?: number;
    percent?: number;
    status?: string;
    description?: string;
    rows?: any[];        // table rows
    items?: any[];       // list items
    html?: string;       // rich text / markdown rendered as HTML
    [key: string]: any;  // allow future extensions
  };
  // Configuration block controlling display and formatting
  config: {
    format?: 'percentage' | 'number' | string;
    color?: string;
    pagination?: any;         // Ant Design table pagination settings or false
    columns?: TableColumn[];  // Table column definitions
    height?: number;          // Chart / container height
    chartType?: string;       // For chart placeholder (line, bar, etc.)
    [key: string]: any;       // Additional feature flags
  };
}
