import React, { useCallback, useState, useEffect, useMemo } from "react";
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
import { Modal, Button, Spin, message, Select } from "antd";
import {
  CloseOutlined,
  FullscreenOutlined,
  PlusOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import "@xyflow/react/dist/style.css";
import "../styles/FlowVisualization.css";
import { apiService } from "../services/api";
import { nodeTypes, orderedNodeTypes } from './nodeTypes';
import { EditableTaskNode, TaskNode } from "./types";
// @ts-ignore
import yaml from 'js-yaml';

interface FlowVisualizationProps {
  visible: boolean;
  onClose: () => void;
  playbookId: string;
  playbookName: string;
  content?: string;
  readOnly?: boolean;
  hideTitle?: boolean;
  onUpdateContent?: (newContent: string) => void;
}

// Minimal metadata retained locally only for icons/colors (no editors/complex config)
const nodeMeta: Record<string, { icon: string; color: string; label: string }> = {
  start: { icon: '🚀', color: '#2563eb', label: 'start' },
  workbook: { icon: '📊', color: '#ff6b35', label: 'workbook' },
  python: { icon: '🐍', color: '#15803d', label: 'python' },
  http: { icon: '🌐', color: '#9333ea', label: 'http' },
  duckdb: { icon: '🦆', color: '#0d9488', label: 'duckdb' },
  postgres: { icon: '🐘', color: '#1d4ed8', label: 'postgres' },
  secrets: { icon: '🔐', color: '#6d28d9', label: 'secrets' },
  playbooks: { icon: '📘', color: '#4b5563', label: 'playbooks' },
  loop: { icon: '🔁', color: '#a16207', label: 'loop' },
  end: { icon: '🏁', color: '#dc2626', label: 'end' },
  log: { icon: '📝', color: '#64748b', label: 'log' },
};

const FlowVisualization: React.FC<FlowVisualizationProps> = ({
  visible,
  onClose,
  playbookId,
  playbookName,
  content,
  readOnly,
  hideTitle,
  onUpdateContent,
}) => {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  // Minimal global edit modal state (only type change + delete)
  const [activeTask, setActiveTask] = useState<EditableTaskNode | null>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [tasks, setTasks] = useState<EditableTaskNode[]>([]);
  const [hasChanges, setHasChanges] = useState(false);

  // Provide nodeTypes directly (already a stable object export)
  const customNodeTypes = useMemo(() => nodeTypes, []);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  // Map legacy or unknown types to supported widget types
  const mapType = (t?: string): EditableTaskNode['type'] => {
    switch ((t || '').toLowerCase()) {
      case 'script':
        return 'python';
      case 'sql':
        return 'duckdb';
      case 'export':
        return 'workbook';
      // keep 'log' as-is now (no remap to start)
      case 'http':
      case 'python':
      case 'workbook':
      case 'duckdb':
      case 'postgres':
      case 'secrets':
      case 'playbooks':
      case 'loop':
      case 'start':
      case 'end':
      case 'log':
        return t as any;
      default:
        return (t as any) || 'workbook';
    }
  };

  // Handle task editing - simplified for direct updates
  const handleEditTask = useCallback(
    (updatedTask: EditableTaskNode) => {
      if (readOnly) return; // prevent edits in read-only
      setTasks((prev) => prev.map((t) => {
        if (t.id === updatedTask.id) {
          // Preserve original id; only update name/config/etc.
          return { ...t, ...updatedTask, id: t.id };
        }
        return t;
      }));
      setNodes((current) => current.map((n) => {
        if (n.id === updatedTask.id) {
          const existingTask: EditableTaskNode = (n.data as any)?.task || { id: updatedTask.id, name: '', type: 'workbook' };
          const merged: EditableTaskNode = { ...existingTask, ...updatedTask, id: existingTask.id };
          return { ...n, type: merged.type, data: { ...n.data, task: merged } } as any;
        }
        return n;
      }));
      setHasChanges(true);
    },
    [setNodes, readOnly]
  );

  // Handle task deletion (moved above createFlowFromTasks to satisfy hooks deps)
  const handleDeleteTask = useCallback((taskId: string) => {
    if (readOnly) return;
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    setHasChanges(true);
    messageApi.success("Component deleted");
  }, [messageApi, readOnly]);

  // Layout constants for auto positioning (breathe like the examples)
  const GRID_COLUMNS = 3;
  const H_SPACING = 420; // was 380
  const V_SPACING = 260; // was 240
  const X_OFFSET = 96;
  const Y_OFFSET = 96;

  // Create flow nodes/edges from tasks - must be defined before recreateFlow
  const createFlowFromTasks = useCallback(
    (tasks: EditableTaskNode[]): { nodes: Node[]; edges: Edge[] } => {
      const flowNodes: Node[] = [];
      const flowEdges: Edge[] = [];

      // Create nodes
      tasks.forEach((task, index) => {
        const x =
          task.position?.x ??
          (index % GRID_COLUMNS) * H_SPACING + X_OFFSET;
        const y =
          task.position?.y ??
          Math.floor(index / GRID_COLUMNS) * V_SPACING + Y_OFFSET;

        flowNodes.push({
          id: task.id,
          type: task.type, // per-type component
          position: { x, y },
          data: {
            task,
            onEdit: handleEditTask,
            onDelete: handleDeleteTask,
            readOnly,
            // onOpen not used (click handler below)
          },
          className: "react-flow__node",
        });
      });

      // Create edges based on dependencies (with arrow markers)
      tasks.forEach((task, index) => {
        const edgeCommon = {
          animated: false,
          className: "flow-edge-solid",
        };

        if (task.dependencies && task.dependencies.length > 0) {
          task.dependencies.forEach((dep) => {
            const sourceTask = tasks.find((t) => t.name === dep);
            if (sourceTask) {
              flowEdges.push({
                id: `edge-${sourceTask.id}-${task.id}`,
                source: sourceTask.id,
                target: task.id,
                ...edgeCommon,
              });
            }
          });
        } else if (index > 0) {
          flowEdges.push({
            id: `edge-${tasks[index - 1].id}-${task.id}`,
            source: tasks[index - 1].id,
            target: task.id,
            ...edgeCommon,
          });
        }
      });

      return { nodes: flowNodes, edges: flowEdges };
    },
    [handleEditTask, handleDeleteTask, readOnly]
  );

  // Recreate flow when tasks change
  const recreateFlow = useCallback(() => {
    const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(tasks);
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [tasks, createFlowFromTasks, setNodes, setEdges]);

  // Handle adding new task
  const handleAddTask = useCallback(() => {
    if (readOnly) return;
    const newTask: EditableTaskNode = {
      id: `task_${Date.now()}`,
      name: 'New Component',
      type: 'workbook',
      description: '',
      enabled: true,
      position: { x: 100 + tasks.length * 50, y: 100 + tasks.length * 50 },
    };

    setTasks((prev) => [...prev, newTask]);
    setHasChanges(true);
    messageApi.success('New component added');
  }, [tasks, messageApi, readOnly]);

  // Re-enable automatic flow recreation for major changes
  useEffect(() => {
    if (tasks.length > 0) {
      recreateFlow();
    }
  }, [tasks.length, recreateFlow]); // Only recreate when task count changes

  const sanitizeId = (s: string) => (s || '')
    .trim()
    .replace(/[^a-zA-Z0-9_-]/g, '_')
    .replace(/_{2,}/g, '_')
    .toLowerCase() || `task_${Date.now()}`;

  const parsePlaybookContent = (raw: string): TaskNode[] => {
    if (!raw || !raw.trim()) return [];
    try {
      const doc: any = yaml.load(raw) || {};
      const list = Array.isArray(doc?.workflow) ? doc.workflow
        : Array.isArray(doc?.tasks) ? doc.tasks
          : [];
      if (!Array.isArray(list)) return [];
      const parsed: TaskNode[] = [];
      list.forEach((entry: any, idx: number) => {
        if (!entry || typeof entry !== 'object') return;
        const rawName: string = entry.desc || entry.name || entry.step || `Task ${idx + 1}`;
        const baseId = sanitizeId(entry.step || entry.name || rawName || `task_${idx + 1}`);
        let uniqueId = baseId;
        let c = 1;
        while (parsed.some(t => t.id === uniqueId)) uniqueId = `${baseId}_${c++}`;
        const t: TaskNode = {
          id: uniqueId,
          name: rawName,
          type: mapType(entry.type || 'workbook'),
          config: undefined,
        } as any;
        const cfg: any = {};
        if (entry.config && typeof entry.config === 'object') Object.assign(cfg, entry.config);
        if (typeof entry.code === 'string') cfg.code = entry.code;
        if (typeof entry.sql === 'string') cfg.sql = entry.sql;
        if (Object.keys(cfg).length) (t as any).config = cfg;
        parsed.push(t);
      });
      return parsed;
    } catch (e) {
      console.warn('YAML parse failed:', e);
      return [];
    }
  };

  const updateWorkflowInYaml = (original: string, taskList: EditableTaskNode[]): string => {
    let doc: any = {};
    try { if (original && original.trim()) doc = yaml.load(original) || {}; } catch { doc = {}; }
    if (!doc || typeof doc !== 'object') doc = {};
    delete doc.tasks;
    delete doc.workflow;

    doc.workflow = taskList.filter(t => (t.name || '').trim()).map(t => {
      const cfg = t.config || {};
      const { code, sql, ...rest } = cfg;
      const stepKey = sanitizeId(t.name || t.id);
      const out: any = { step: stepKey };
      if (t.name && t.name.trim() && t.name.trim() !== stepKey) out.desc = t.name.trim();
      if (t.type && t.type !== 'workbook') out.type = t.type;
      if (Object.keys(rest).length) out.config = rest;
      if (code) out.code = code;
      if (sql) out.sql = sql;
      return out;
    });

    try {
      return yaml.dump(doc, { noRefs: true, lineWidth: 120 });
    } catch (e) {
      console.error('Failed to dump YAML:', e);
      return original;
    }
  };

  const handleSaveWorkflow = useCallback(async () => {
    try {
      setLoading(true);
      const updatedYaml = updateWorkflowInYaml(content || '', tasks);
      if (onUpdateContent) onUpdateContent(updatedYaml);

      if (playbookId && playbookId !== 'new') {
        try {
          await apiService.savePlaybookContent(playbookId, updatedYaml);
          messageApi.success('Workflow saved to backend');
        } catch (persistErr) {
          console.error('Backend persistence failed:', persistErr);
          messageApi.warning('YAML updated locally, backend save failed');
        }
      } else {
        messageApi.info('YAML updated. Create & save playbook from main editor to persist');
      }

      setHasChanges(false);
    } catch (error) {
      console.error(error);
      messageApi.error('Failed to save workflow');
    } finally {
      setLoading(false);
    }
  }, [tasks, content, onUpdateContent, messageApi, playbookId]);

  const loadPlaybookFlow = async () => {
    setLoading(true);
    try {
      let contentToUse = content;

      if (!contentToUse && playbookId) {
        contentToUse = await apiService.getPlaybookContent(playbookId);
      }

      if (contentToUse && contentToUse.trim()) {
        const parsedTasks = parsePlaybookContent(contentToUse);
        if (parsedTasks.length === 0) {
          messageApi.warning(
            "No workflow steps found in this playbook. Showing demo flow."
          );

          let demoTasks: EditableTaskNode[] = [];
          if (
            playbookId.toLowerCase().includes("weather") ||
            playbookName.toLowerCase().includes("weather")
          ) {
            demoTasks = [
              { id: "demo-1", name: "Fetch Weather Data", type: 'http', enabled: true },
              { id: "demo-2", name: "Process Weather Info", type: 'python', enabled: true },
              { id: "demo-3", name: "Generate Weather Report", type: 'workbook', enabled: true },
            ];
          } else if (
            playbookId.toLowerCase().includes("database") ||
            playbookId.toLowerCase().includes("sql")
          ) {
            demoTasks = [
              { id: "demo-1", name: "Connect to Database", type: 'duckdb', enabled: true },
              { id: "demo-2", name: "Query Data", type: 'duckdb', enabled: true },
              { id: "demo-3", name: "Export Results", type: 'workbook', enabled: true },
            ];
          } else {
            demoTasks = [
              { id: "demo-1", name: "Initialize Process", type: 'start', enabled: true },
              { id: "demo-2", name: "Process Data", type: 'python', enabled: true },
              { id: "demo-3", name: "Export Results", type: 'workbook', enabled: true },
            ];
          }

          setTasks(demoTasks);
          const { nodes: flowNodes, edges: flowEdges } =
            createFlowFromTasks(demoTasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
        } else {
          const editableTasks: EditableTaskNode[] = parsedTasks.map((task) => ({
            ...task,
            type: mapType(task.type),
            enabled: true,
          }));
          setTasks(editableTasks);
          const { nodes: flowNodes, edges: flowEdges } =
            createFlowFromTasks(editableTasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
          messageApi.success(
            `Successfully parsed ${parsedTasks.length} workflow steps from ${playbookName}!`
          );
        }
      } else {
        messageApi.warning(`No content found for playbook: ${playbookName}`);
        const demoTasks: EditableTaskNode[] = [
          { id: "empty-1", name: "No Content Available", type: 'start', enabled: true },
        ];
        setTasks(demoTasks);
        const { nodes: flowNodes, edges: flowEdges } =
          createFlowFromTasks(demoTasks);
        setNodes(flowNodes);
        setEdges(flowEdges);
      }
    } catch (error) {
      messageApi.error(
        `Failed to load playbook flow for ${playbookName}.`
      );
      const errorTasks: EditableTaskNode[] = [
        { id: "error-1", name: "Failed to Load Playbook", type: 'start', enabled: true },
        { id: "error-2", name: "Check API Connection", type: 'python', enabled: true },
      ];
      setTasks(errorTasks);
      const { nodes: flowNodes, edges: flowEdges } =
        createFlowFromTasks(errorTasks);
      setNodes(flowNodes);
      setEdges(flowEdges);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible && (playbookId || content)) {
      loadPlaybookFlow();
    }
  }, [visible, playbookId, content]);

  const handleFullscreen = () => setFullscreen((f) => !f);

  const defaultEdgeOptions = {
    type: "smoothstep" as const,
    animated: false,
    style: { stroke: "#a0aec0", strokeWidth: 2 },
  };

  const flowInner = (
    <div className="FlowVisualization flow-layout-root">
      {contextHolder}
      {/* Content container now full-width; dock moved inside canvas wrapper */}
      <div className="flow-content-container">
        {loading ? (
          <div className="flow-loading-container">
            <Spin size="large" />
            <div className="flow-loading-text">Loading playbook flow...</div>
          </div>
        ) : (
          <div className="react-flow-wrapper">
            {/* Left Vertical Dock now inside bordered wrapper */}
            <div className="flow-dock">
              {!readOnly && (
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={handleAddTask}
                  size="small"
                  className="flow-dock-btn"
                  title="Add Component"
                />
              )}
              {!readOnly && hasChanges && (
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  onClick={handleSaveWorkflow}
                  loading={loading}
                  size="small"
                  className="flow-dock-btn"
                  title="Save Workflow"
                />
              )}
              <div className="flow-dock-separator" />
              <Button
                type="text"
                icon={<FullscreenOutlined />}
                onClick={handleFullscreen}
                title="Toggle Fullscreen"
                className="flow-dock-btn"
                size="small"
              />
              <Button
                type="text"
                icon={<CloseOutlined />}
                onClick={onClose}
                title="Close"
                className="flow-dock-btn"
                size="small"
              />
            </div>
            <div className="FlowVisualization__flow-canvas-container" style={{ width: '100%', height: '500px' }}>
              <ReactFlow
                nodes={nodes.map(n => ({ ...n, data: { ...n.data, readOnly } }))}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={(e, node) => {
                  // Explicit global flag set by HTTP edit button to bypass type modal
                  if ((window as any).__skipNextNodeModal) {
                    (window as any).__skipNextNodeModal = false;
                    return;
                  }
                  const target = e.target as HTMLElement;
                  if (target && target.closest('.http-edit-btn')) return;
                  const task = (node.data as any)?.task;
                  if (task) setActiveTask(task);
                }}
                nodeTypes={customNodeTypes}
                defaultEdgeOptions={defaultEdgeOptions}
                connectionLineStyle={{ stroke: "#cbd5e1", strokeWidth: 2 }}
                fitView
                fitViewOptions={{ padding: 0.18 }}
                attributionPosition="bottom-left"
                key={`flow-${tasks.length}-${tasks.map((t) => `${t.id}-${t.type}`).join("-")}-${readOnly ? 'ro' : 'rw'}`}
              >
                <Controls />
                <MiniMap
                  nodeColor={(node) => {
                    const type = (node.data as any)?.task?.type ?? 'workbook';
                    return nodeMeta[type]?.color || '#8c8c8c';
                  }}
                  pannable
                  zoomable
                  style={{
                    background: "white",
                    border: "1px solid #e5e7eb",
                    borderRadius: 8,
                  }}
                />
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={22}
                  size={1}
                  color="#eaeef5"
                />
              </ReactFlow>
            </div>
          </div>
        )}
      </div>
    </div>
  );
  if (!visible) return null;
  return <>
    {flowInner}
    <Modal
      open={!!activeTask}
      onCancel={() => setActiveTask(null)}
      footer={null}
      title={activeTask ? `Node: ${activeTask.name}` : ''}
      width={420}
    >
      {activeTask && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 500 }}>Type</label>
            <Select
              disabled={!!readOnly}
              value={activeTask.type}
              onChange={(val) => handleEditTask({ ...activeTask, type: val })}
              options={orderedNodeTypes.map(t => ({ value: t, label: `${nodeMeta[t]?.icon || ''} ${nodeMeta[t]?.label || t}` }))}
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
            <Button onClick={() => setActiveTask(null)}>Close</Button>
            {!readOnly && (
              <Button danger onClick={() => { if (activeTask) { handleDeleteTask(activeTask.id); setActiveTask(null); } }}>Delete</Button>
            )}
          </div>
        </div>
      )}
    </Modal>
  </>;
};

export default FlowVisualization;
