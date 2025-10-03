// Common types used across the application

export interface ServerStatus {
  status: "ok" | "healthy" | "error" | "warning" | string;
  message: string;
  timestamp: string;
}

export interface PlaybookData {
  id: string;
  name: string;
  resource_type: string;
  resource_version: string;
  meta: any;
  timestamp: string;
  status: "active" | "inactive" | "draft";
  tasks_count: number;
  updated_at: string;
  description?: string;
  created_at?: string;
}

export interface ExecutionData {
  id: string;
  playbook_id: string;
  playbook_name: string;
  status: "running" | "completed" | "failed" | "pending";
  start_time: string;
  end_time?: string;
  duration?: number;
  progress: number;
  result?: any;
  error?: string;
  events?: Array<{
    event_id: string;
    event_type: string;
    node_name: string;
    status: string;
    timestamp: string;
    duration: number;
  }>;
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
