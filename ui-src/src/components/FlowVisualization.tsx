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
  BackgroundVariant,
  useReactFlow,
  ReactFlowProvider,
  ConnectionMode,
  MarkerType,
  type OnConnect,
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
import { edgeTypes } from './edges'; // custom edge components
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
  onPositionsChange?: (positions: Record<string, { x: number; y: number }>) => void;
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
  onPositionsChange,
}) => {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();
  const [tasks, setTasks] = useState<EditableTaskNode[]>([]);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const reactFlowInstance = useReactFlow();
  const { screenToFlowPosition } = reactFlowInstance;
  const [type] = useDnD();

  // Track node position changes and update tasks
  const handleNodesChange = useCallback((changes: any[]) => {
    onNodesChange(changes);

    // Update task positions when nodes are moved
    changes.forEach((change) => {
      if (change.type === 'position' && change.position && !change.dragging) {
        setTasks((prevTasks) => {
          const updatedTasks = prevTasks.map((task) =>
            task.id === change.id
              ? { ...task, position: change.position }
              : task
          );

          // Notify parent of position changes
          if (onPositionsChange) {
            const positions: Record<string, { x: number; y: number }> = {};
            updatedTasks.forEach(task => {
              if (task.position) {
                positions[task.id] = task.position;
              }
            });
            onPositionsChange(positions);
          }

          return updatedTasks;
        });
      }
    });
  }, [onNodesChange, onPositionsChange]);

  // Force ReactFlow to recalculate viewport after sidebar renders
  useEffect(() => {
    if (visible && reactFlowInstance) {
      setTimeout(() => {
        reactFlowInstance.fitView({ padding: 0.18 });
      }, 50);
    }
  }, [visible, reactFlowInstance]);

  const onConnect: OnConnect = useCallback(
    (params) => setEdges((eds) => addEdge({
      ...params,
      type: 'buttonedge',
    }, eds)),
    [setEdges],
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
    },
    [setNodes, readOnly]
  );

  // Handle task deletion (moved above createFlowFromTasks to satisfy hooks deps)
  const handleDeleteTask = useCallback((taskId: string) => {
    if (readOnly) return;
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
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

        // Create edges from workflow connections
        if (task.config?.next) {
          const nextSteps = Array.isArray(task.config.next) ? task.config.next : [task.config.next];
          nextSteps.forEach((nextItem: any) => {
            const targetStep = nextItem.step || nextItem;
            if (targetStep && typeof targetStep === 'string') {
              flowEdges.push({
                id: `${task.id}-${targetStep}`,
                source: task.id,
                target: targetStep,
                type: 'buttonedge',
              });
            }
          });
        }

        // Also handle 'case' blocks if present
        if (task.config?.case) {
          const cases = Array.isArray(task.config.case) ? task.config.case : [task.config.case];
          cases.forEach((caseItem: any) => {
            if (caseItem.then) {
              const thenSteps = Array.isArray(caseItem.then) ? caseItem.then : [caseItem.then];
              thenSteps.forEach((thenItem: any) => {
                const targetStep = thenItem.step || thenItem;
                if (targetStep && typeof targetStep === 'string') {
                  flowEdges.push({
                    id: `${task.id}-${targetStep}-case`,
                    source: task.id,
                    target: targetStep,
                    type: 'buttonedge',
                  });
                }
              });
            }
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
      // Fetch playbook data from API
      const response = await apiService.getPlaybook(playbookId);
      console.log('API response:', response);

      // Parse the playbook content if it's YAML/JSON string
      let playbookData: any = response;
      if (response.content) {
        try {
          // Parse YAML content
          playbookData = yaml.load(response.content);
          console.log('Parsed playbook from content:', playbookData);
        } catch (parseError) {
          console.error('Error parsing playbook content:', parseError);
          throw new Error('Failed to parse playbook content');
        }
      }

      console.log('Playbook data:', playbookData);
      console.log('Has workflow?', playbookData?.workflow);
      console.log('Has workbook?', playbookData?.workbook);

      // Parse workflow steps into tasks
      const workflowSteps = playbookData?.workflow || playbookData?.workbook || [];
      console.log('Workflow steps:', workflowSteps);

      // If no workflow steps, throw error with helpful message
      if (workflowSteps.length === 0) {
        console.error('Playbook structure:', Object.keys(playbookData));
        throw new Error(`No workflow/workbook found. Available keys: ${Object.keys(playbookData).join(', ')}`);
      }

      const loadedTasks: EditableTaskNode[] = workflowSteps.map((step: any, index: number) => {
        const stepType = step.tool || step.type || 'workbook';
        return {
          id: step.step || `step-${index}`,
          name: step.desc || step.step || `Step ${index + 1}`,
          type: mapType(stepType),
          enabled: true,
          config: step,
          position: step.position, // Use saved position if available
        };
      });

      setTasks(loadedTasks);
      const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(loadedTasks);
      setNodes(flowNodes);
      setEdges(flowEdges);
    } catch (error) {
      console.error('Error loading playbook:', error);
      messageApi.error('Failed to load playbook');

      // Fallback to demo tasks
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
      const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(demoTasks);
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
            <ReactFlow
              nodes={nodes.map(n => ({ ...n, data: { ...n.data, readOnly } }))}
              edges={edges}
              onNodesChange={handleNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onInit={(instance) => {
                // Force viewport update after ReactFlow initializes
                setTimeout(() => instance.fitView({ padding: 0.18 }), 100);
              }}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              snapToGrid={false}
              snapGrid={[15, 15]}
              elementsSelectable={!readOnly}
              nodesConnectable={!readOnly}
              nodesDraggable={!readOnly}
              connectionMode={ConnectionMode.Strict}
              connectionRadius={20}
              isValidConnection={(connection) => connection.source !== connection.target}
              fitView
              fitViewOptions={{ padding: 0.18 }}
              attributionPosition="bottom-left"
              className={isDraggingOver ? 'dragging-over' : ''}
              key={`flow-${tasks.length}-${tasks.map((t) => `${t.id}-${t.type}`).join("-")}-${readOnly ? 'ro' : 'rw'}`}
            >
              <Controls />
              <MiniMap
                nodeColor="#3b82f6"
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
