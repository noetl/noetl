import React, { useCallback, useState, useEffect } from "react";
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
} from "@xyflow/react";
import {
  Modal,
  Button,
  Spin,
  message,
  Input,
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

interface FlowVisualizationProps {
  visible: boolean;
  onClose: () => void;
  playbookId: string;
  playbookName: string;
  content?: string; // Optional content to use instead of fetching from API
  embedded?: boolean; // when true render inline instead of Modal
}

interface TaskNode {
  id: string;
  name: string;
  type: string;
  config?: any;
  dependencies?: string[];
  description?: string;
  enabled?: boolean;
}

interface EditableTaskNode extends TaskNode {
  position?: { x: number; y: number };
}

// Custom editable node component
const EditableNode: React.FC<NodeProps> = ({ data, id, selected }) => {
  const { task, onEdit, onDelete } = data as {
    task: EditableTaskNode;
    onEdit: (task: EditableTaskNode) => void;
    onDelete: (id: string) => void;
  };

  // Ensure we get the latest nodeType based on current task type
  const nodeType =
    nodeTypes[task?.type as keyof typeof nodeTypes] || nodeTypes.default;

  const handleNameChange = (value: string) => {
    const updatedTask = { ...task, name: value };
    onEdit?.(updatedTask);
  };

  const handleTypeChange = (value: string) => {
    const updatedTask = { ...task, type: value };
    onEdit?.(updatedTask);
  };

  const handleDescriptionChange = (value: string) => {
    const updatedTask = { ...task, description: value };
    onEdit?.(updatedTask);
  };

  const nodeClass = `flow-node ${task?.type || "default"} ${selected ? "selected" : "unselected"
    }`;

  return (
    <div className={nodeClass}>
      {/* connection handles */}
      <Handle
        type="target"
        position={Position.Left}
        className="flow-node-handle flow-node-handle-target"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="flow-node-handle flow-node-handle-source"
      />

      {/* Inline toolbar shown only when node is selected */}
      {selected && (
        <div
          className="flow-node-toolbar nodrag"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Type selector moved here */}
          <Select
            value={task?.type || "default"}
            onChange={handleTypeChange}
            size="small"
            className="flow-node-type-select flow-node-toolbar-type-select"
            popupClassName="flow-node-type-dropdown"
            dropdownMatchSelectWidth={false}
            getPopupContainer={() => document.body}
            options={[
              { value: "log", label: "📝 Log" },
              { value: "http", label: "🌐 HTTP" },
              { value: "sql", label: "🗄️ SQL" },
              { value: "script", label: "⚙️ Script" },
              { value: "secret", label: "🔑 Secret" },
              { value: "export", label: "📤 Export" },
              { value: "python", label: "🐍 Python" },
              { value: "workbook", label: "📊 Workbook" },
              { value: "default", label: "📄 Default" },
            ]}
          />
          <Popconfirm
            title="Delete this component?"
            onConfirm={(e) => {
              e?.stopPropagation();
              onDelete?.(id);
            }}
            okText="Yes"
            cancelText="No"
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              className="flow-node-toolbar-button"
              onClick={(e) => e.stopPropagation()}
            />
          </Popconfirm>
        </div>
      )}

      {/* Header: icon + status pill now inline above separator */}
      <div className="flow-node-header">
        <span className="flow-node-icon" aria-hidden>
          {nodeType.icon}
        </span>
        <div className={`flow-node-status inline ${task?.type || "default"}`}>
          {(task?.type ? task.type.charAt(0).toUpperCase() + task.type.slice(1) : "Default")}
        </div>
      </div>

      {/* Task name - always editable */}
      <div className="flow-node-name">
        <span className="flow-node-field-label">Name</span>
        <Input
          value={task?.name || "Unnamed Task"}
          onChange={(e) => handleNameChange(e.target.value)}
          placeholder="Task name"
          size="small"
          className="flow-node-name-input nodrag"
        />
      </div>

      {/* Description - always editable */}
      <div className="flow-node-description">
        <span className="flow-node-field-label">Description</span>
        <Input.TextArea
          value={task?.description || ""}
          onChange={(e) => handleDescriptionChange(e.target.value)}
          placeholder="Description (optional)"
          size="small"
          rows={2}
          className="flow-node-description-input nodrag"
        />
      </div>
    </div>
  );
};

const nodeTypes = {
  log: { color: "#52c41a", icon: "📝" },
  http: { color: "#1890ff", icon: "🌐" },
  sql: { color: "#722ed1", icon: "🗄️" },
  script: { color: "#fa8c16", icon: "⚙️" },
  secret: { color: "#eb2f96", icon: "🔑" },
  export: { color: "#13c2c2", icon: "📤" },
  python: { color: "#3776ab", icon: "🐍" },
  workbook: { color: "#ff6b35", icon: "📊" },
  default: { color: "#8c8c8c", icon: "📄" },
};

const FlowVisualization: React.FC<FlowVisualizationProps> = ({
  visible,
  onClose,
  playbookId,
  playbookName,
  content,
  embedded,
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

  // Handle task editing - simplified for direct updates
  const handleEditTask = useCallback(
    (updatedTask: EditableTaskNode) => {
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
    [setNodes]
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
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    setHasChanges(true);
    messageApi.success("Component deleted");
  }, [messageApi]);

  // Handle adding new task
  const handleAddTask = useCallback(() => {
    const newTask: EditableTaskNode = {
      id: `task_${Date.now()}`,
      name: "New Task",
      type: "default",
      description: "",
      enabled: true,
      position: { x: 100 + tasks.length * 50, y: 100 + tasks.length * 50 },
    };

    setTasks((prev) => [...prev, newTask]);
    setHasChanges(true);
    messageApi.success("New component added");
  }, [tasks, messageApi]);

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
              type: "default",
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
              type: "default",
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
              currentTask.type = (typeMatch[1] || typeMatch[2] || "").trim();
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
              { id: "demo-1", name: "Fetch Weather Data", type: "http", enabled: true },
              { id: "demo-2", name: "Process Weather Info", type: "script", enabled: true },
              { id: "demo-3", name: "Generate Weather Report", type: "export", enabled: true },
            ];
          } else if (
            playbookId.toLowerCase().includes("database") ||
            playbookId.toLowerCase().includes("sql")
          ) {
            demoTasks = [
              { id: "demo-1", name: "Connect to Database", type: "sql", enabled: true },
              { id: "demo-2", name: "Query Data", type: "sql", enabled: true },
              { id: "demo-3", name: "Export Results", type: "export", enabled: true },
            ];
          } else {
            demoTasks = [
              { id: "demo-1", name: "Initialize Process", type: "log", enabled: true },
              { id: "demo-2", name: "Process Data", type: "script", enabled: true },
              { id: "demo-3", name: "Export Results", type: "export", enabled: true },
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
          { id: "empty-1", name: "No Content Available", type: "log", enabled: true },
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
        { id: "error-1", name: "Failed to Load Playbook", type: "log", enabled: true },
        { id: "error-2", name: "Check API Connection", type: "script", enabled: true },
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
    if ((visible || embedded) && (playbookId || content)) {
      loadPlaybookFlow();
    }
  }, [visible, embedded, playbookId, content]);

  const handleFullscreen = () => setFullscreen((f) => !f);

  const defaultEdgeOptions = {
    type: "smoothstep" as const,
    animated: false,
    style: { stroke: "#a0aec0", strokeWidth: 2 },
  };

  const flowInner = (
    <>
      {/* Toolbar */}
      <div className="flow-toolbar-container">
        <Space>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleAddTask}
            size="small"
          >
            Add Component
          </Button>
          {hasChanges && (
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSaveWorkflow}
              loading={loading}
              size="small"
            >
              Save Workflow
            </Button>
          )}
        </Space>

        <Space>
          <Button
            type="text"
            icon={<FullscreenOutlined />}
            onClick={handleFullscreen}
            title="Toggle Fullscreen"
            className="flow-toolbar-button"
            size="small"
          />
          <Button
            type="text"
            icon={<CloseOutlined />}
            onClick={onClose}
            title="Close"
            className="flow-toolbar-button"
            size="small"
          />
        </Space>
      </div>

      <div className="flow-content-container">
        {loading ? (
          <div className="flow-loading-container">
            <Spin size="large" />
            <div className="flow-loading-text">Loading playbook flow...</div>
          </div>
        ) : (
          <div className="react-flow-wrapper">
            <ReactFlow
              nodes={nodes}
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
                .join("-")}`}
            >
              <Controls />
              <MiniMap
                nodeColor={(node) => {
                  const type = (node.data as any)?.task?.type ?? "default";
                  return (
                    nodeTypes[type as keyof typeof nodeTypes]?.color ||
                    nodeTypes.default.color
                  );
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
        )}
      </div>
    </>
  );

  // Render inline when embedded flag is set, otherwise use Modal
  if (embedded) {
    return (
      <div
        className={
          fullscreen
            ? "flow-modal-fullscreen flow-embedded"
            : "flow-modal-windowed flow-embedded"
        }
        style={{
          width: fullscreen ? "95vw" : "80vw",
          height: fullscreen ? "85vh" : "70vh",
          margin: "24px auto",
        }}
      >
        {contextHolder}
        <div
          className="flow-modal-title"
          style={{ display: "flex", alignItems: "center", gap: 12 }}
        >
          <span className="flow-modal-title-icon">🔄</span>
          <span>Flow Editor - {playbookName}</span>
          {hasChanges && <Tag color="orange">Unsaved Changes</Tag>}
        </div>
        {flowInner}
      </div>
    );
  }

  return (
    <>
      {contextHolder}
      <Modal
        title={
          <div className="flow-modal-title">
            <span className="flow-modal-title-icon">🔄</span>
            <span>Flow Editor - {playbookName}</span>
            {hasChanges && <Tag color="orange">Unsaved Changes</Tag>}
          </div>
        }
        open={visible}
        onCancel={onClose}
        footer={null}
        closable={false}
        width={fullscreen ? "95vw" : "80vw"}
        className={fullscreen ? "flow-modal-fullscreen" : "flow-modal-windowed"}
        styles={
          fullscreen
            ? { body: { height: "85vh", padding: 0, overflow: "hidden" } }
            : { body: { height: "70vh", padding: 0, overflow: "hidden" } }
        }
      >
        {flowInner}
      </Modal>
    </>
  );
};

export default FlowVisualization;
