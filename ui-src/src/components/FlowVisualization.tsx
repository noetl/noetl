import React, { useCallback, useState, useEffect, memo } from "react";
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
  NodeTypes,
  NodeProps,
  Handle,
  Position,
  MarkerType,
  useReactFlow,
} from "@xyflow/react";
import {
  Modal,
  Button,
  Spin,
  message,
  Select,
  Space,
  Popconfirm,
  Tag,
} from "antd";
import {
  CloseOutlined,
  FullscreenOutlined,
  DeleteOutlined,
  PlusOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import "@xyflow/react/dist/style.css";
import "../styles/FlowVisualization.css";
import { apiService } from "../services/api";
// Import modular node type definitions
import { nodeTypeMap, orderedNodeTypes } from './nodeTypes';
import { EditableTaskNode, TaskNode } from "./types";
import { EditableNode } from "./EditableNode";

interface FlowVisualizationProps {
  visible: boolean;
  onClose: () => void;
  playbookId: string;
  playbookName: string;
  content?: string; // Optional content to use instead of fetching from API
  readOnly?: boolean; // NEW: render in read-only (view) mode
  hideTitle?: boolean; // NEW: suppress internal title (avoid duplicates)
}



const FlowVisualization: React.FC<FlowVisualizationProps> = ({
  visible,
  onClose,
  playbookId,
  playbookName,
  content,
  readOnly,
  hideTitle,
}) => {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  // antd message with context (avoid static API)
  const [messageApi, contextHolder] = message.useMessage();

  // Editing state
  const [tasks, setTasks] = useState<EditableTaskNode[]>([]);
  const [hasChanges, setHasChanges] = useState(false);

  // Define custom node types for ReactFlow
  const customNodeTypes: NodeTypes = {
    editableNode: EditableNode,
  };

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
      case 'log':
        return 'start';
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
        return t as any;
      default:
        return 'workbook';
    }
  };

  // Handle task editing - simplified for direct updates
  const handleEditTask = useCallback(
    (updatedTask: EditableTaskNode) => {
      if (readOnly) return; // prevent edits in read-only
      setTasks((prev) =>
        prev.map((t) => (t.id === updatedTask.id ? updatedTask : t))
      );

      // Update nodes directly using ReactFlow's setNodes
      setNodes((currentNodes) =>
        currentNodes.map((node) =>
          node.id === updatedTask.id
            ? { ...node, data: { ...node.data, task: updatedTask } }
            : node
        )
      );

      setHasChanges(true);
    },
    [setNodes, readOnly]
  );

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
          type: "editableNode",
          position: { x, y },
          data: {
            task,
            onEdit: handleEditTask,
            onDelete: handleDeleteTask,
            label: null,
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
    [handleEditTask]
  );

  // Recreate flow when tasks change
  const recreateFlow = useCallback(() => {
    const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(tasks);
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [tasks, createFlowFromTasks, setNodes, setEdges]);

  // Handle task deletion
  const handleDeleteTask = useCallback((taskId: string) => {
    if (readOnly) return;
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    setHasChanges(true);
    messageApi.success("Component deleted");
  }, [messageApi, readOnly]);

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

  // Save entire workflow
  const handleSaveWorkflow = useCallback(async () => {
    try {
      setLoading(true);
      // await apiService.savePlaybookWorkflow(playbookId, tasks);
      setHasChanges(false);
      messageApi.success("Workflow saved successfully!");
    } catch (error) {
      messageApi.error("Failed to save workflow");
    } finally {
      setLoading(false);
    }
  }, [tasks, playbookId, messageApi]);

  const parsePlaybookContent = (content: string): TaskNode[] => {
    try {
      const lines = content.split("\n");
      const tasks: TaskNode[] = [];
      let currentTask: Partial<TaskNode> = {};
      let inWorkflowSection = false;
      let taskIndex = 0;
      let workflowIndent = 0;
      let inNestedLogic = false;
      let nestedLevel = 0;

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();
        const indent = line.length - line.trimStart().length;

        if (
          trimmed === "workflow:" ||
          trimmed.startsWith("workflow:") ||
          trimmed === "tasks:" ||
          trimmed.startsWith("tasks:") ||
          trimmed === "steps:" ||
          trimmed.startsWith("steps:")
        ) {
          inWorkflowSection = true;
          workflowIndent = indent;
          continue;
        }

        if (inWorkflowSection) {
          if (
            trimmed &&
            indent <= workflowIndent &&
            !trimmed.startsWith("-") &&
            trimmed.includes(":") &&
            !trimmed.startsWith("#")
          ) {
            break;
          }

          if (trimmed.match(/^(next|then|else|when):/)) {
            if (!inNestedLogic) {
              inNestedLogic = true;
              nestedLevel = indent;
            }
            continue;
          }

          if (
            inNestedLogic &&
            indent === workflowIndent + 2 &&
            trimmed.startsWith("- step:")
          ) {
            inNestedLogic = false;
          }

          if (
            trimmed.startsWith("- step:") &&
            !inNestedLogic &&
            indent === workflowIndent + 2
          ) {
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
            }

            const stepMatch = trimmed.match(/step:\s*([^'"]+)/);
            const taskName = stepMatch
              ? stepMatch[1].trim()
              : `Step ${taskIndex + 1}`;

            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, "_").toLowerCase(),
              name: taskName,
              type: 'workbook',
            };
          } else if (
            (trimmed.startsWith("- name:") ||
              (trimmed.startsWith("-") && trimmed.includes("name:"))) &&
            !inNestedLogic
          ) {
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
            }

            const nameMatch = trimmed.match(
              /name:\s*['"](.*?)['"]|name:\s*(.+)/
            );
            const taskName = nameMatch
              ? (nameMatch[1] || nameMatch[2] || "").trim()
              : `Task ${taskIndex + 1}`;

            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, "_").toLowerCase(),
              name: taskName,
              type: 'workbook',
            };
          } else if (
            trimmed.startsWith("desc:") &&
            currentTask.name &&
            !inNestedLogic
          ) {
            const descMatch = trimmed.match(
              /desc:\s*['"](.*?)['"]|desc:\s*(.+)/
            );
            if (descMatch) {
              const description = (descMatch[1] || descMatch[2] || "")
                .trim()
                .replace(/^["']|["']$/g, "");
              const originalName = currentTask.name;
              currentTask.name = description;
              if (
                !currentTask.id ||
                currentTask.id ===
                originalName.replace(/[^a-zA-Z0-9]/g, "_").toLowerCase()
              ) {
                currentTask.id = originalName
                  .replace(/[^a-zA-Z0-9]/g, "_")
                  .toLowerCase();
              }
            }
          } else if (
            trimmed.startsWith("type:") &&
            currentTask.name &&
            !inNestedLogic
          ) {
            const typeMatch = trimmed.match(
              /type:\s*['"](.*?)['"]|type:\s*([^'"]+)/
            );
            if (typeMatch) {
              currentTask.type = mapType((typeMatch[1] || typeMatch[2] || '').trim());
            }
          }

          if (inNestedLogic && indent <= nestedLevel) {
            inNestedLogic = false;
          }
        }
      }

      if (currentTask.name) {
        tasks.push(currentTask as TaskNode);
      }

      return tasks;
    } catch (error) {
      return [];
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
                nodeTypes={customNodeTypes}
                defaultEdgeOptions={defaultEdgeOptions}
                connectionLineStyle={{ stroke: "#cbd5e1", strokeWidth: 2 }}
                fitView
                fitViewOptions={{ padding: 0.18 }}
                attributionPosition="bottom-left"
                key={`flow-${tasks.length}-${tasks
                  .map((t) => `${t.id}-${t.type}`)
                  .join("-")}-${readOnly ? 'ro' : 'rw'}`}
              >
                <Controls />
                <MiniMap
                  nodeColor={(node) => {
                    const type = (node.data as any)?.task?.type ?? 'workbook';
                    return nodeTypeMap[type]?.color || '#8c8c8c';
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
  return flowInner;
};

export default FlowVisualization;
