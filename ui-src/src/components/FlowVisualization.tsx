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
  ConnectionMode,
  MarkerType,
  ConnectionLineType,
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
import { nodeTypes } from './nodes'; // simplified source
import { EditableTaskNode, TaskNode } from "./types";
import { DnDProvider, useDnD } from "./DnDContext";
import Sidebar from "./Sidebar";
// @ts-ignore
import yaml from 'js-yaml';

interface FlowVisualizationProps {
  visible: boolean;
  onClose: () => void;
  playbookId: string;
  readOnly?: boolean;
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
  readOnly,
}) => {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();
  const [tasks, setTasks] = useState<EditableTaskNode[]>([]);
  const [hasChanges, setHasChanges] = useState(false);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const { screenToFlowPosition } = useReactFlow();
  const [type] = useDnD();

  const onConnect = useCallback(
    (params: Connection) => {
      // Prevent self-connections
      if (params.source === params.target) {
        messageApi.warning('Cannot connect a node to itself');
        return;
      }

      // Check for duplicate connections
      const isDuplicate = edges.some(
        edge => edge.source === params.source && edge.target === params.target
      );

      if (isDuplicate) {
        messageApi.warning('Connection already exists');
        return;
      }

      setEdges((eds) => addEdge({
        ...params,
        type: 'smoothstep',
        animated: false,
        style: { stroke: '#94a3b8', strokeWidth: 1.5 },
        deletable: true,
        focusable: true,
      }, eds));
      setHasChanges(true);
      messageApi.success('Nodes connected');
    },
    [setEdges, edges, messageApi]
  );

  // Connection start/end handlers for visual feedback
  const onConnectStart = useCallback(() => {
    setIsConnecting(true);
  }, []);

  const onConnectEnd = useCallback(() => {
    setIsConnecting(false);
  }, []);

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



  // Create flow nodes/edges from tasks - must be defined before recreateFlow
  const createFlowFromTasks = useCallback(
    (tasks: EditableTaskNode[]): { nodes: Node[]; edges: Edge[] } => {
      const flowNodes: Node[] = [];
      const flowEdges: Edge[] = [];

      // Layout constants for centered grid layout
      const GRID_COLUMNS = 3;
      const H_SPACING = 360;
      const V_SPACING = 200;
      const X_OFFSET = 300; // Increased to center the grid
      const Y_OFFSET = 96;

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
            ...task.config, // Spread config fields into data
            name: task.name,
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
          deletable: true,
          focusable: true,
          selectable: true,
          type: 'smoothstep',
          style: { stroke: '#94a3b8', strokeWidth: 1.5 },
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

  // Re-enable automatic flow recreation for major changes
  useEffect(() => {
    if (tasks.length > 0) {
      recreateFlow();
    }
  }, [tasks.length, recreateFlow]); // Only recreate when task count changes

  const loadPlaybookFlow = async () => {
    setLoading(true);
    try {

      let demoTasks: EditableTaskNode[] = [
        { id: "demo-1", name: "Start Workflow", type: 'start', enabled: true },
        { id: "demo-2", name: "HTTP Request", type: 'http', enabled: true },
        { id: "demo-3", name: "Python Transform", type: 'python', enabled: true },
        { id: "demo-4", name: "DuckDB Analytics", type: 'duckdb', enabled: true },
        { id: "demo-5", name: "Postgres Storage", type: 'postgres', enabled: true },
        { id: "demo-6", name: "Call Sub-Playbook", type: 'playbooks', enabled: true },
        { id: "demo-7", name: "Workbook Task", type: 'workbook', enabled: true },
        { id: "demo-9", name: "End Workflow", type: 'end', enabled: true },
      ];

      setTasks(demoTasks);
      const { nodes: flowNodes, edges: flowEdges } =
        createFlowFromTasks(demoTasks);
      setNodes(flowNodes);
      setEdges(flowEdges);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible && (playbookId)) {
      loadPlaybookFlow();
    }
  }, [visible, playbookId]);

  const handleFullscreen = () => setFullscreen((f) => !f);

  const defaultEdgeOptions = {
    type: "smoothstep" as const,
    animated: false,
    style: { stroke: "#94a3b8", strokeWidth: 1.5 },
    deletable: true,
    focusable: true,
    selectable: true,
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
            {/* Connection helper overlay */}
            {isConnecting && !readOnly && (
              <div style={{
                position: 'absolute',
                top: 10,
                // left: '50%',
                // transform: 'translateX(-50%)',
                zIndex: 1000,
                background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
                color: 'white',
                padding: '12px 24px',
                borderRadius: '12px',
                boxShadow: '0 8px 24px rgba(59, 130, 246, 0.4)',
                fontSize: '14px',
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                animation: 'slideDown 0.3s ease-out',
              }}>
                <span style={{ fontSize: '18px' }}>🔗</span>
                <span>Drag to a target node to connect • Press ESC to cancel</span>
              </div>
            )}

            {/* Hint overlay for edge operations */}
            {!readOnly && (
              <div style={{
                position: 'absolute',
                bottom: 10,
                // left: '50%',
                // transform: 'translateX(-50%)',
                zIndex: 1000,
                background: 'rgba(15, 23, 42, 0.85)',
                backdropFilter: 'blur(8px)',
                color: 'white',
                padding: '8px 16px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: 400,
                display: 'flex',
                alignItems: 'center',
                gap: '16px',
                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
              }}>
                <span>💡 Click edge to select • Delete key or × button to remove</span>
              </div>
            )}

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
                onEdgesChange={(changes) => {
                  onEdgesChange(changes);
                  setHasChanges(true);
                }}
                onConnect={onConnect}
                onConnectStart={onConnectStart}
                onConnectEnd={onConnectEnd}
                onDrop={onDrop}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                nodeTypes={nodeTypes}
                defaultEdgeOptions={defaultEdgeOptions}
                connectionMode={ConnectionMode.Loose}
                connectionLineStyle={{
                  stroke: "#3b82f6",
                  strokeWidth: 2,
                  strokeDasharray: '8,4'
                }}
                connectionLineType={ConnectionLineType.SmoothStep}
                connectionRadius={8}
                snapToGrid={false}
                snapGrid={[15, 15]}
                deleteKeyCode="Delete"
                multiSelectionKeyCode="Shift"
                edgesReconnectable={!readOnly}
                edgesFocusable={!readOnly}
                elementsSelectable={!readOnly}
                nodesConnectable={!readOnly}
                nodesDraggable={!readOnly}
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
