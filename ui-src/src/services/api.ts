import axios from 'axios';

// API Base URL - will be proxied by Vite to FastAPI backend
const API_BASE_URL = process.env.NODE_ENV === 'development' ? 'http://localhost:8081/api' : '/api';

// API Client instance
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// Type definitions for API responses
export interface ServerStatus {
  status: string;
  message: string;
  timestamp: string;
}

export interface PlaybookData {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
  status: 'active' | 'inactive' | 'draft';
  tasks_count: number;
}

export interface ExecutionData {
  id: string;
  playbook_id: string;
  playbook_name: string;
  status: 'running' | 'completed' | 'failed' | 'pending';
  start_time: string;
  end_time?: string;
  duration?: number;
  progress: number;
  result?: any;
  error?: string;
}

export interface DashboardStats {
  total_playbooks: number;
  total_executions: number;
  active_executions: number;
  success_rate: number;
  recent_executions: ExecutionData[];
}

export interface VisualizationWidget {
  id: string;
  type: 'chart' | 'table' | 'metric' | 'text';
  title: string;
  data: any;
  config: any;
}

// API Service class
class APIService {
  // Health check
  async getHealth(): Promise<ServerStatus> {
    const response = await apiClient.get('/health');
    return response.data;
  }

  // Dashboard APIs
  async getDashboardStats(): Promise<DashboardStats> {
    const response = await apiClient.get('/dashboard/stats');
    return response.data;
  }

  async getDashboardWidgets(): Promise<VisualizationWidget[]> {
    const response = await apiClient.get('/dashboard/widgets');
    return response.data;
  }

  // Playbook APIs
  async getPlaybooks(): Promise<PlaybookData[]> {
    const response = await apiClient.get('/catalog/playbooks');
    return response.data;
  }

  async getPlaybook(id: string): Promise<PlaybookData> {
    const response = await apiClient.get(`/catalog/playbooks/${id}`);
    return response.data;
  }

  async createPlaybook(data: Partial<PlaybookData>): Promise<PlaybookData> {
    const response = await apiClient.post('/catalog/playbooks', data);
    return response.data;
  }

  async updatePlaybook(id: string, data: Partial<PlaybookData>): Promise<PlaybookData> {
    const response = await apiClient.put(`/catalog/playbooks/${id}`, data);
    return response.data;
  }

  async deletePlaybook(id: string): Promise<void> {
    await apiClient.delete(`/catalog/playbooks/${id}`);
  }

  // Execution APIs
  async getExecutions(): Promise<ExecutionData[]> {
    const response = await apiClient.get('/executions');
    return response.data;
  }

  async getExecution(id: string): Promise<ExecutionData> {
    const response = await apiClient.get(`/executions/${id}`);
    return response.data;
  }

  async executePlaybook(playbookId: string, params?: any): Promise<ExecutionData> {
    const response = await apiClient.post(`/executions/run`, {
      playbook_id: playbookId,
      parameters: params || {}
    });
    return response.data;
  }

  async stopExecution(id: string): Promise<void> {
    await apiClient.post(`/executions/${id}/stop`);
  }

  // Editor APIs
  async getPlaybookContent(id: string): Promise<string> {
    const response = await apiClient.get(`/catalog/playbooks/${id}/content`);
    return response.data.content;
  }

  async savePlaybookContent(id: string, content: string): Promise<void> {
    await apiClient.put(`/catalog/playbooks/${id}/content`, { content });
  }

  async validatePlaybook(content: string): Promise<{ valid: boolean; errors?: string[] }> {
    const response = await apiClient.post('/catalog/playbooks/validate', { content });
    return response.data;
  }

  // Catalog APIs
  async getCatalogWidgets(): Promise<VisualizationWidget[]> {
    const response = await apiClient.get('/catalog/widgets');
    return response.data;
  }

  async searchPlaybooks(query: string): Promise<PlaybookData[]> {
    const response = await apiClient.get(`/playbooks/search?q=${encodeURIComponent(query)}`);
    return response.data;
  }
}

export const apiService = new APIService();
export default apiService;
