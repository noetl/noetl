export interface TaskNode {
  id: string;
  name: string;
  type: string;
  config?: any;
  dependencies?: string[];
  description?: string;
  enabled?: boolean;
}

export interface EditableTaskNode extends TaskNode {
  position?: { x: number; y: number };
}