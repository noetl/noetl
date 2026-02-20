import axios from "axios";
import {
  DashboardStats,
  ExecutionData,
  PlaybookData,
  ServerStatus,
  CredentialData,
} from "../types";
import { CreatePlaybookResponse } from "./api.types";
import { resolveGatewayBaseUrl } from "./gatewayBaseUrl";

const SESSION_TOKEN_KEY = "session_token";

// In gateway-only mode, NoETL APIs are proxied under /noetl
const getApiBaseUrl = () => `${resolveGatewayBaseUrl()}/noetl`;

const API_BASE_URL = getApiBaseUrl();

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120 * 1000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(SESSION_TOKEN_KEY);
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
    config.headers["X-Session-Token"] = token;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem(SESSION_TOKEN_KEY);
      localStorage.removeItem("user_info");
    }
    console.error("API Error:", error);
    return Promise.reject(error);
  },
);

// export interface ServerStatus {
//   status: string;
//   message: string;
//   timestamp: string;
// }
//
//  export interface EventData {
//    event_id: string;
//    event_type: string;
//    node_id: string;
//    node_name: string;
//    node_type: string;
//    status: string;
//    duration: number;
//    timestamp: string;
//    input_context?: any;
//    output_result?: any;
//    metadata?: any;
//    error?: string;
//  }
//
// export interface PlaybookData {
//   id: string;
//   name: string;
//   description?: string;
//   created_at: string;
//   updated_at: string;
//   status: 'active' | 'inactive' | 'draft';
//   tasks_count: number;
//   events?: EventData[];
// }
//
// export interface ExecutionData {
//   id: string;
//   playbook_id: string;
//   playbook_name: string;
//   status: 'running' | 'completed' | 'failed' | 'pending';
//   start_time: string;
//   end_time?: string;
//   duration?: number;
//   progress: number;
//   result?: any;
//   error?: string;
//   events?: Array<{
//   event_id: string;
//   event_type: string;
//   node_name: string;
//   status: string;
//   timestamp: string;
//   duration: number;
//   }>;
// }
//
// export interface DashboardStats {
//   total_playbooks: number;
//   total_executions: number;
//   active_executions: number;
//   success_rate: number;
//   recent_executions: ExecutionData[];
// }
//
// export interface VisualizationWidget {
//   id: string;
//   type: 'chart' | 'table' | 'metric' | 'text';
//   title: string;
//   data: any;
//   config: any;
// }

class APIService {
  private normalizeExecution(raw: any): ExecutionData {
    const normalizedStatus =
      typeof raw?.status === "string" ? raw.status.toLowerCase() : raw?.status;
    return {
      ...raw,
      execution_id: raw?.execution_id != null ? String(raw.execution_id) : "",
      status: normalizedStatus,
    };
  }

  private normalizeExecutionList(rawList: any): ExecutionData[] {
    if (!Array.isArray(rawList)) return [];
    return rawList.map((item) => this.normalizeExecution(item));
  }

  async getHealth(): Promise<ServerStatus> {
    const response = await apiClient.get("/health");
    return response.data;
  }

  async getDashboardStats(): Promise<DashboardStats> {
    const response = await apiClient.get("/dashboard/stats");
    return response.data;
  }

  async getPlaybooks(): Promise<PlaybookData[]> {
    const response = await apiClient.post("/catalog/list", {
      "resource_type": "Playbook",
    });
    // todo: remove once backend is fixed
    if (response.data.entries) {
      for (let entry of response.data.entries) {
        entry.status = entry.status || "active";
      }
    }
    return response.data.entries;
  }

  async getPlaybook(path: string): Promise<PlaybookData> {
    const response = await apiClient.post(`/catalog/resource`, {
      "path": path,
      "version": "latest"
    });
    return response.data;
  }

  async createPlaybook(yaml: string): Promise<CreatePlaybookResponse> {
    // const base64Content = btoa(unescape(encodeURIComponent(yaml)));
    const response = await apiClient.post("/catalog/register", { content: yaml, resource_type: "Playbook" });
    return response.data;
  }

  async registerPlaybook(playbookData: any): Promise<CreatePlaybookResponse> {
    // If it's already a string (YAML or JSON text), use it directly
    const content = typeof playbookData === 'string' ? playbookData : JSON.stringify(playbookData);
    const response = await apiClient.post("/catalog/register", { content, resource_type: "Playbook" });
    return response.data;
  }

  async updatePlaybook(
    id: string,
    data: Partial<PlaybookData>,
  ): Promise<PlaybookData> {
    const response = await apiClient.put(`/catalog/playbook`, data, {
      params: { playbook_id: id },
    });
    return response.data;
  }

  async deletePlaybook(id: string): Promise<void> {
    await apiClient.delete(`/catalog/playbooks/${id}`);
  }

  async getExecutions(): Promise<ExecutionData[]> {
    const response = await apiClient.get("/executions");
    return this.normalizeExecutionList(response.data);
  }

  async getExecution(id: string, params?: {
    page?: number;
    page_size?: number;
    since_event_id?: number;
    event_type?: string;
  }): Promise<ExecutionData> {
    // Use primary execution detail endpoint under /api/executions with pagination support
    const response = await apiClient.get(`/executions/${id}`, { params });
    return this.normalizeExecution(response.data);
  }

  async getExecutionEvents(id: string, params?: {
    page?: number;
    page_size?: number;
    since_event_id?: number;
    event_type?: string;
  }): Promise<{
    events: any[];
    pagination: {
      page: number;
      page_size: number;
      total_events: number;
      total_pages: number;
      has_next: boolean;
      has_prev: boolean;
    };
  }> {
    // Get paginated events for incremental loading
    const response = await apiClient.get(`/executions/${id}`, { params });
    return {
      events: response.data.events || [],
      pagination: response.data.pagination || {
        page: 1,
        page_size: params?.page_size || 100,
        total_events: response.data.events?.length || 0,
        total_pages: 1,
        has_next: false,
        has_prev: false
      }
    };
  }

  async analyzeExecution(
    id: string,
    payload?: {
      max_events?: number;
      event_sample_size?: number;
      include_playbook_content?: boolean;
    },
  ): Promise<any> {
    const response = await apiClient.post(`/executions/${id}/analyze`, payload || {});
    return response.data;
  }

  async analyzeExecutionWithAI(
    id: string,
    payload?: {
      max_events?: number;
      event_sample_size?: number;
      include_playbook_content?: boolean;
      include_event_rows?: boolean;
      event_rows_limit?: number;
      include_event_log_rows?: boolean;
      event_log_rows_limit?: number;
      analysis_playbook_path?: string;
      gcp_auth_credential?: string;
      openai_secret_path?: string;
      model?: string;
      include_patch_diff?: boolean;
      auto_fix_mode?: "report" | "dry_run" | "apply";
      approval_required?: boolean;
      approved?: boolean;
      timeout_seconds?: number;
      poll_interval_ms?: number;
    },
  ): Promise<any> {
    const response = await apiClient.post(`/executions/${id}/analyze/ai`, payload || {});
    return response.data;
  }

  async executePlaybook(
    catalog_id: string,
    params?: any,
  ): Promise<ExecutionData> {
    // v2 engine now served under /api; keep path relative to API base
    const response = await apiClient.post(`/execute`, {
      catalog_id,
      payload: params || {},
    });
    return response.data;
  }

  async executePlaybookWithPayload(
    requestBody: any,
  ): Promise<{ execution_id: string }> {
    const response = await apiClient.post("/execute", requestBody);
    return response.data;
  }

  async stopExecution(id: string): Promise<void> {
    await apiClient.post(`/executions/${id}/stop`);
  }

  async cancelExecution(id: string, reason?: string, cascade: boolean = true): Promise<any> {
    const response = await apiClient.post(`/executions/${id}/cancel`, {
      reason,
      cascade
    });
    return response.data;
  }

  async getPlaybookContent(id: string): Promise<string | undefined> {
    try {
      const response = await apiClient.get(`/catalog/playbook/content`, {
        params: { playbook_id: id },
      });
      return response.data.content as string;
    } catch (e) {
      console.warn("API call failed for playbook content:", e);
    }
  }

  async savePlaybookContent(id: string, content: string): Promise<void> {
    await apiClient.put(`/catalog/playbook/content`, { content }, {
      params: { playbook_id: id },
    });
  }

  async validatePlaybook(
    content: string,
  ): Promise<{ valid: boolean; errors?: string[] }> {
    const response = await apiClient.post("/catalog/playbooks/validate", {
      content,
    });
    return response.data;
  }

  async getPlaybookTestSuite(suiteId: string): Promise<{
    suite_id: string;
    file_path: string;
    playbook_path: string;
    tests: any[];
    metadata: Record<string, any>;
    updated_at: string;
  }> {
    const encoded = suiteId.split("/").map(encodeURIComponent).join("/");
    const response = await apiClient.get(`/playbook-tests/suites/${encoded}`);
    return response.data;
  }

  async savePlaybookTestSuite(
    suiteId: string,
    payload: {
      playbook_path: string;
      tests: any[];
      metadata?: Record<string, any>;
    },
  ): Promise<{
    suite_id: string;
    file_path: string;
    playbook_path: string;
    tests: any[];
    metadata: Record<string, any>;
    updated_at: string;
  }> {
    const encoded = suiteId.split("/").map(encodeURIComponent).join("/");
    const response = await apiClient.put(`/playbook-tests/suites/${encoded}`, {
      playbook_path: payload.playbook_path,
      tests: payload.tests || [],
      metadata: payload.metadata || {},
    });
    return response.data;
  }

  async deletePlaybookTestSuite(suiteId: string): Promise<{ status: string; suite_id: string; file_path: string }> {
    const encoded = suiteId.split("/").map(encodeURIComponent).join("/");
    const response = await apiClient.delete(`/playbook-tests/suites/${encoded}`);
    return response.data;
  }

  async searchPlaybooks(query: string): Promise<PlaybookData[]> {
    const q = query.trim().toLowerCase();
    if (!q) {
      return this.getPlaybooks();
    }

    // Backend does not expose /catalog/playbooks/search in gateway mode.
    // Use catalog/list and filter client-side to avoid noisy 404s.
    const response = await apiClient.post("/catalog/list", {
      resource_type: "Playbook",
    });
    const entries: PlaybookData[] = response.data.entries || [];

    for (const entry of entries) {
      entry.status = entry.status || "active";
    }

    return entries.filter((playbook) => {
      const path = (playbook.path || "").toLowerCase();
      const description = (playbook.payload?.metadata?.description || "").toLowerCase();
      const name = (playbook.payload?.metadata?.name || "").toLowerCase();
      return path.includes(q) || description.includes(q) || name.includes(q);
    });
  }

  async getCredentials(type?: string): Promise<CredentialData[]> {
    const params: any = {};
    if (type) {
      params.type = type;
    }
    const response = await apiClient.get("/credentials", { params });
    return response.data.items || [];
  }

  async getCredential(identifier: string, includeData: boolean = false): Promise<CredentialData> {
    const response = await apiClient.get(`/credentials/${identifier}`, {
      params: { include_data: includeData }
    });
    return response.data;
  }

  async searchCredentials(query: string): Promise<CredentialData[]> {
    const response = await apiClient.get("/credentials", {
      params: { q: query }
    });
    return response.data.items || [];
  }

  async createOrUpdateCredential(data: any): Promise<CredentialData> {
    const response = await apiClient.post("/credentials", data);
    return response.data;
  }

  async deleteCredential(identifier: string): Promise<void> {
    await apiClient.delete(`/credentials/${identifier}`);
  }
}

export const apiService = new APIService();
export default apiService;
