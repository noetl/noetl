import axios from "axios";
import {
  DashboardStats,
  ExecutionData,
  PlaybookData,
  ServerStatus,
} from "../types";
const getApiBaseUrl = () => {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  if (import.meta.env.MODE === "development") {
    if ((window as any).__API_BASE_URL__) {
      return (window as any).__API_BASE_URL__;
    }
    return "http://localhost:8082/api";
  }
  return "/api";
};

const API_BASE_URL = getApiBaseUrl();

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
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
  async getHealth(): Promise<ServerStatus> {
    const response = await apiClient.get("/health");
    return response.data;
  }

  async getDashboardStats(): Promise<DashboardStats> {
    const response = await apiClient.get("/dashboard/stats");
    return response.data;
  }

  async getPlaybooks(): Promise<PlaybookData[]> {
    const response = await apiClient.get("/catalog/playbooks");
    return response.data;
  }

  async getCatalogList(): Promise<PlaybookData[]> {
    const response = await apiClient.get("/catalog/list");
    return response.data.entries;
  }

  async getPlaybook(id: string): Promise<PlaybookData> {
    const response = await apiClient.get(`/catalog/playbooks?id=${id}`);
    return response.data;
  }

  async createPlaybook(data: Partial<PlaybookData>): Promise<PlaybookData> {
    const response = await apiClient.post("/catalog/register", data);
    return response.data;
  }

  async updatePlaybook(
    id: string,
    data: Partial<PlaybookData>,
  ): Promise<PlaybookData> {
    const response = await apiClient.put(`/catalog/playbooks/${id}`, data);
    return response.data;
  }

  async deletePlaybook(id: string): Promise<void> {
    await apiClient.delete(`/catalog/playbooks/${id}`);
  }

  async getExecutions(): Promise<ExecutionData[]> {
    const response = await apiClient.get("/executions");
    return response.data;
  }

  async getExecution(id: string): Promise<ExecutionData> {
    const response = await apiClient.get(`/executions/${id}`);
    return response.data;
  }

  async executePlaybook(
    playbookId: string,
    params?: any,
  ): Promise<ExecutionData> {
    const response = await apiClient.post(`/executions/run`, {
      playbook_id: playbookId,
      parameters: params || {},
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

  async getPlaybookContent(id: string): Promise<string | undefined> {
    try {
      const response = await apiClient.get(`/catalog/playbooks/${encodeURIComponent(id)}/content`);
      return response.data.content as string;
    } catch (e) {
      console.warn("API call failed for playbook content:", e);
    }
  }

  async savePlaybookContent(id: string, content: string): Promise<void> {
    await apiClient.put(`/catalog/playbooks/${id}/content`, { content });
  }

  async validatePlaybook(
    content: string,
  ): Promise<{ valid: boolean; errors?: string[] }> {
    const response = await apiClient.post("/catalog/playbooks/validate", {
      content,
    });
    return response.data;
  }

  async searchPlaybooks(query: string): Promise<PlaybookData[]> {
    const response = await apiClient.get(
      `/catalog/playbooks/search?q=${encodeURIComponent(query)}`,
    );
    return response.data;
  }
}

export const apiService = new APIService();
export default apiService;
