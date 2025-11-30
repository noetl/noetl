import React, { useCallback, useState, useEffect, useMemo, useRef } from "react";
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
  useReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import { Modal, Button, Spin, message, Select } from "antd";
import {
  CloseOutlined,
  FullscreenOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import "@xyflow/react/dist/style.css";
import "../styles/FlowVisualization.css";
import { apiService } from "../services/api";
import { nodeTypes } from './nodeTypes'; // simplified source
import { EditableTaskNode, TaskNode } from "./types";
import { DnDProvider, useDnD } from "./DnDContext";
import Sidebar from "./Sidebar";
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

// Generate unique IDs for new nodes
let nodeId = 0;
const getNodeId = () => `node_${nodeId++}_${Date.now()}`;

// Inner component that has access to React Flow hooks
const FlowVisualizationInner: React.FC<FlowVisualizationProps> = ({
  visible,
  onClose,
  playbookId,
  playbookName,
  content,
  readOnly,
  hideTitle,
  onUpdateContent,
}) => {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [activeTask, setActiveTask] = useState<EditableTaskNode | null>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [tasks, setTasks] = useState<EditableTaskNode[]>([]);
  const [hasChanges, setHasChanges] = useState(false);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const { screenToFlowPosition } = useReactFlow();
  const [type] = useDnD();

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  // Drag and drop handlers with visual feedback
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    setIsDraggingOver(true);
  }, []);

  const onDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setIsDraggingOver(false);
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setIsDraggingOver(false);

      if (!type || readOnly) {
        return;
      }

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newTask: EditableTaskNode = {
        id: getNodeId(),
        name: `${type} node`,
        type: type as any,
        enabled: true,
        position,
      };

      setTasks((prev) => [...prev, newTask]);
      setHasChanges(true);
      messageApi.success(`${type} node added`);
    },
    [screenToFlowPosition, type, readOnly, messageApi]
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

  // Layout constants for centered grid layout
  const GRID_COLUMNS = 3;
  const H_SPACING = 360;
  const V_SPACING = 200;
  const X_OFFSET = 300; // Increased to center the grid
  const Y_OFFSET = 96;

  // Create flow nodes/edges from tasks - must be defined before recreateFlow
  const createFlowFromTasks = useCallback(
    (tasks: EditableTaskNode[]): { nodes: Node[]; edges: Edge[] } => {
      const flowNodes: Node[] = [];
      const flowEdges: Edge[] = [];

      // Create nodes in centered grid layout
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

  // Auto-update YAML content when tasks change
  useEffect(() => {
    if (tasks.length > 0 && hasChanges && onUpdateContent) {
      const updatedYaml = updateWorkflowInYaml(content || '', tasks);
      onUpdateContent(updatedYaml);
    }
  }, [tasks, hasChanges]);

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
        // Infer type from step name if no tool/type specified (for start/end)
        const stepName = (entry.step || '').toLowerCase();
        const inferredType = (stepName === 'start' || stepName === 'end') ? stepName : 'workbook';
        const t: TaskNode = {
          id: uniqueId,
          name: rawName,
          type: mapType(entry.tool || entry.type || inferredType),
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
              { id: "demo-1", name: "Start Weather Pipeline", type: 'start', enabled: true },
              { id: "demo-2", name: "Fetch Weather API", type: 'http', enabled: true },
              { id: "demo-3", name: "Transform Weather Data", type: 'python', enabled: true },
              { id: "demo-4", name: "Analyze with DuckDB", type: 'duckdb', enabled: true },
              { id: "demo-5", name: "Store in Postgres", type: 'postgres', enabled: true },
              { id: "demo-6", name: "Generate Report", type: 'workbook', enabled: true },
              { id: "demo-7", name: "End Pipeline", type: 'end', enabled: true },
            ];
          } else if (
            playbookId.toLowerCase().includes("database") ||
            playbookId.toLowerCase().includes("sql")
          ) {
            demoTasks = [
              { id: "demo-1", name: "Start", type: 'start', enabled: true },
              { id: "demo-2", name: "Load Secrets", type: 'secrets', enabled: true },
              { id: "demo-3", name: "Query DuckDB", type: 'duckdb', enabled: true },
              { id: "demo-4", name: "Query Postgres", type: 'postgres', enabled: true },
              { id: "demo-5", name: "Process Results", type: 'python', enabled: true },
              { id: "demo-6", name: "Loop Through Records", type: 'loop', enabled: true },
              { id: "demo-7", name: "Export Data", type: 'workbook', enabled: true },
              { id: "demo-8", name: "End", type: 'end', enabled: true },
            ];
          } else {
            demoTasks = [
              { id: "demo-1", name: "Start Workflow", type: 'start', enabled: true },
              { id: "demo-2", name: "HTTP Request", type: 'http', enabled: true },
              { id: "demo-3", name: "Python Transform", type: 'python', enabled: true },
              { id: "demo-4", name: "DuckDB Analytics", type: 'duckdb', enabled: true },
              { id: "demo-5", name: "Postgres Storage", type: 'postgres', enabled: true },
              { id: "demo-6", name: "Call Sub-Playbook", type: 'playbooks', enabled: true },
              { id: "demo-7", name: "Workbook Task", type: 'workbook', enabled: true },
              { id: "demo-8", name: "Iterator Loop", type: 'loop', enabled: true },
              { id: "demo-9", name: "End Workflow", type: 'end', enabled: true },
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
          { id: "empty-1", name: "Start", type: 'start', enabled: true },
          { id: "empty-2", name: "HTTP Example", type: 'http', enabled: true },
          { id: "empty-3", name: "Python Example", type: 'python', enabled: true },
          { id: "empty-4", name: "DuckDB Example", type: 'duckdb', enabled: true },
          { id: "empty-5", name: "Postgres Example", type: 'postgres', enabled: true },
          { id: "empty-6", name: "Playbooks Example", type: 'playbooks', enabled: true },
          { id: "empty-7", name: "Workbook Example", type: 'workbook', enabled: true },
          { id: "empty-8", name: "Loop Example", type: 'loop', enabled: true },
          { id: "empty-9", name: "End", type: 'end', enabled: true },
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
    <div className="FlowVisualization flow-layout-root" style={{ display: 'flex', height: fullscreen ? '100vh' : '600px' }}>
      {contextHolder}
      {/* Sidebar for drag and drop */}
      {!readOnly && <Sidebar />}

      {/* Main flow content */}
      <div className="flow-content-container" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {loading ? (
          <div className="flow-loading-container">
            <Spin size="large" />
            <div className="flow-loading-text">Loading playbook flow...</div>
          </div>
        ) : (
          <div className="react-flow-wrapper" ref={reactFlowWrapper} style={{ flex: 1, position: 'relative' }}>
            {/* Control buttons moved to top right */}
            <div className="flow-controls" style={{ position: 'absolute', top: 10, right: 10, zIndex: 10, display: 'flex', gap: 8 }}>
              <Button
                type="default"
                icon={<FullscreenOutlined />}
                onClick={handleFullscreen}
                title="Toggle Fullscreen"
                size="small"
              />
              <Button
                type="default"
                icon={<CloseOutlined />}
                onClick={onClose}
                title="Close"
                size="small"
              />
            </div>
            <div className="FlowVisualization__flow-canvas-container" style={{ width: '100%', height: '100%' }}>
              <ReactFlow
                nodes={nodes.map(n => ({ ...n, data: { ...n.data, readOnly } }))}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onDrop={onDrop}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                nodeTypes={nodeTypes}
                defaultEdgeOptions={defaultEdgeOptions}
                connectionLineStyle={{ stroke: "#cbd5e1", strokeWidth: 2 }}
                fitView
                fitViewOptions={{ padding: 0.18 }}
                attributionPosition="bottom-left"
                className={isDraggingOver ? 'dragging-over' : ''}
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
              options={Object.keys(nodeMeta).map(t => ({ value: t, label: `${nodeMeta[t]?.icon || ''} ${nodeMeta[t]?.label || t}` }))}
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

// Main wrapper component with providers
const FlowVisualization: React.FC<FlowVisualizationProps> = (props) => {
  return (
    <ReactFlowProvider>
      <DnDProvider>
        <FlowVisualizationInner {...props} />
      </DnDProvider>
    </ReactFlowProvider>
  );
};

export default FlowVisualization;
