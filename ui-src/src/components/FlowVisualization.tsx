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
  Tooltip,
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

  console.log("EditableNode render - task:", task, "nodeType:", nodeType);

  const handleNameChange = (value: string) => {
    const updatedTask = { ...task, name: value };
    onEdit?.(updatedTask);
  };

  const handleTypeChange = (value: string) => {
    console.log("Type change requested:", value, "for task:", task.id);
    const updatedTask = { ...task, type: value };
    console.log("Updated task:", updatedTask);
    onEdit?.(updatedTask);
  };

  const handleDescriptionChange = (value: string) => {
    const updatedTask = { ...task, description: value };
    onEdit?.(updatedTask);
  };

  const nodeClass = `flow-node ${task?.type || 'default'} ${selected ? 'selected' : 'unselected'}`;

  return (
    <div className={nodeClass}>
      {/* Delete button - always visible */}
      <div className="flow-node-delete">
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
            onClick={(e) => e.stopPropagation()}
            className="flow-node-delete-button"
          />
        </Popconfirm>
      </div>

      {/* Task icon and type selector */}
      <div className="flow-node-header">
        <div className="flow-node-icon">
          {nodeType.icon}
        </div>
        <Select
          value={task?.type || "default"}
          onChange={(value) => {
            console.log("Select onChange triggered with value:", value);
            handleTypeChange(value);
          }}
          size="small"
          className="flow-node-type-select nodrag"
          dropdownClassName="flow-node-type-dropdown"
          placeholder="Select type"
          showSearch={false}
        >
          <Select.Option value="log">📝 Log</Select.Option>
          <Select.Option value="http">🌐 HTTP</Select.Option>
          <Select.Option value="sql">🗄️ SQL</Select.Option>
          <Select.Option value="script">⚙️ Script</Select.Option>
          <Select.Option value="secret">🔑 Secret</Select.Option>
          <Select.Option value="export">📤 Export</Select.Option>
          <Select.Option value="python">🐍 Python</Select.Option>
          <Select.Option value="workbook">📊 Workbook</Select.Option>
          <Select.Option value="default">📄 Default</Select.Option>
        </Select>
      </div>

      {/* Task name - always editable */}
      <div className="flow-node-name">
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
        <Input.TextArea
          value={task?.description || ""}
          onChange={(e) => handleDescriptionChange(e.target.value)}
          placeholder="Description (optional)"
          size="small"
          rows={2}
          className="flow-node-description-input nodrag"
        />
      </div>

      {/* Status indicator */}
      <div className={`flow-node-status ${task?.type || 'default'}`}>
        {task?.type?.toUpperCase() || "DEFAULT"} COMPONENT
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
}) => {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  // Editing state
  const [tasks, setTasks] = useState<EditableTaskNode[]>([]);
  const [hasChanges, setHasChanges] = useState(false);

  // Define custom node types for ReactFlow
  const customNodeTypes: NodeTypes = {
    editableNode: EditableNode,
  };

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),

    [setEdges],
  );

  // Handle task editing - simplified for direct updates
  const handleEditTask = useCallback(
    (updatedTask: EditableTaskNode) => {
      console.log("handleEditTask called with:", updatedTask);
      setTasks((prev) => {
        console.log("Previous tasks:", prev);
        const newTasks = prev.map((t) =>
          t.id === updatedTask.id ? updatedTask : t,
        );
        console.log("New tasks:", newTasks);
        return newTasks;
      });

      // Update nodes directly using ReactFlow's setNodes
      setNodes((currentNodes) => {
        console.log("Updating nodes, current nodes:", currentNodes.length);
        const updatedNodes = currentNodes.map((node) => {
          if (node.id === updatedTask.id) {
            return {
              ...node,
              data: { ...node.data, task: updatedTask },
            };
          }
          return node;
        });
        console.log("Updated nodes:", updatedNodes);
        return updatedNodes;
      });

      setHasChanges(true);
    },
    [setNodes],
  );

  // Create flow nodes/edges from tasks - must be defined before recreateFlow
  const createFlowFromTasks = useCallback(
    (tasks: EditableTaskNode[]): { nodes: Node[]; edges: Edge[] } => {
      const flowNodes: Node[] = [];
      const flowEdges: Edge[] = [];

      // Create nodes
      tasks.forEach((task, index) => {
        const nodeType =
          nodeTypes[task.type as keyof typeof nodeTypes] || nodeTypes.default;

        // Use stored position or calculate new position
        const x = task.position?.x || (index % 3) * 300 + 100;
        const y = task.position?.y || Math.floor(index / 3) * 150 + 100;

        flowNodes.push({
          id: task.id,
          type: "editableNode",
          position: { x, y },
          data: {
            task,
            onEdit: handleEditTask,
            onDelete: handleDeleteTask,
            label: null, // We handle the label inside the custom component
          },
          className: "react-flow__node",
        });
      });

      // Create edges based on dependencies
      tasks.forEach((task, index) => {
        if (task.dependencies && task.dependencies.length > 0) {
          task.dependencies.forEach((dep) => {
            const sourceTask = tasks.find((t) => t.name === dep);
            if (sourceTask) {
              flowEdges.push({
                id: `edge-${sourceTask.id}-${task.id}`,
                source: sourceTask.id,
                target: task.id,
                animated: false,
                className: "flow-edge-solid",
              });
            }
          });
        } else if (index > 0) {
          // If no explicit dependencies, connect to previous task
          flowEdges.push({
            id: `edge-${tasks[index - 1].id}-${task.id}`,
            source: tasks[index - 1].id,
            target: task.id,
            animated: false,
            className: "flow-edge-solid",
          });
        }
      });

      return { nodes: flowNodes, edges: flowEdges };
    },
    [handleEditTask],
  );

  // Recreate flow when tasks change
  const recreateFlow = useCallback(() => {
    console.log("Recreating flow with tasks:", tasks.length);
    const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(tasks);
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [tasks, createFlowFromTasks, setNodes, setEdges]);

  // Handle task deletion
  const handleDeleteTask = useCallback((taskId: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    setHasChanges(true);
    message.success("Component deleted");
  }, []);

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
    message.success("New component added");
  }, [tasks]);

  // Re-enable automatic flow recreation for major changes
  useEffect(() => {
    if (tasks.length > 0) {
      console.log("Tasks changed, recreating flow:", tasks.length);
      recreateFlow();
    }
  }, [tasks.length, recreateFlow]); // Only recreate when task count changes

  // Save entire workflow
  const handleSaveWorkflow = useCallback(async () => {
    try {
      setLoading(true);
      // Here you would implement saving the workflow back to the playbook
      // This is a placeholder for now
      console.log("Saving workflow with tasks:", tasks);

      // You could call an API endpoint to save the updated workflow
      // await apiService.savePlaybookWorkflow(playbookId, tasks);

      setHasChanges(false);
      message.success("Workflow saved successfully!");
    } catch (error) {
      console.error("Error saving workflow:", error);
      message.error("Failed to save workflow");
    } finally {
      setLoading(false);
    }
  }, [tasks, playbookId]);

  const parsePlaybookContent = (content: string): TaskNode[] => {
    try {
      console.log("PARSING PLAYBOOK CONTENT");
      console.log("Content length:", content.length);
      console.log("Content preview (first 500 chars):");
      console.log(content.substring(0, 500));

      const lines = content.split("\n");
      console.log("Total lines:", lines.length);

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

        // Debug key lines
        if (
          i < 20 &&
          (trimmed.includes("workflow") ||
            trimmed.includes("step") ||
            trimmed.includes("desc") ||
            trimmed.includes("type") ||
            trimmed.includes("tasks"))
        ) {
          console.log(`Line ${i}: [indent:${indent}] "${trimmed}"`);
        }

        // Look for workflow/tasks/steps section
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
          console.log(
            "Found workflow section at line",
            i,
            "with indent",
            workflowIndent,
          );
          continue;
        }

        if (inWorkflowSection) {
          // Check if we've left the workflow section
          if (
            trimmed &&
            indent <= workflowIndent &&
            !trimmed.startsWith("-") &&
            trimmed.includes(":") &&
            !trimmed.startsWith("#")
          ) {
            console.log("Left workflow section at line", i, ":", trimmed);
            break;
          }

          // Detect nested logic sections (next:, then:, else:, when:)
          if (trimmed.match(/^(next|then|else|when):/)) {
            if (!inNestedLogic) {
              inNestedLogic = true;
              nestedLevel = indent;
              console.log(
                "Entering nested logic at line",
                i,
                "level",
                nestedLevel,
                ":",
                trimmed,
              );
            }
            continue;
          }

          // If we're in nested logic, check if we're back to main workflow level
          if (
            inNestedLogic &&
            indent === workflowIndent + 2 &&
            trimmed.startsWith("- step:")
          ) {
            inNestedLogic = false;
            console.log("Exiting nested logic at line", i);
          }

          // Process main workflow steps (not nested conditional steps)
          if (
            trimmed.startsWith("- step:") &&
            !inNestedLogic &&
            indent === workflowIndent + 2
          ) {
            // Save previous task if exists
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
              console.log("Saved main task:", currentTask.name);
            }

            // Extract step name
            const stepMatch = trimmed.match(/step:\s*([^'"]+)/);
            const taskName = stepMatch
              ? stepMatch[1].trim()
              : `Step ${taskIndex + 1}`;

            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, "_").toLowerCase(),
              name: taskName,
              type: "default",
            };
            console.log(
              "Started main task:",
              taskName,
              "[id:",
              currentTask.id,
              "]",
            );
          } else if (
            (trimmed.startsWith("- name:") ||
              (trimmed.startsWith("-") && trimmed.includes("name:"))) &&
            !inNestedLogic
          ) {
            // Handle tasks: format
            // Save previous task if exists
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
            }

            // Start new task
            const nameMatch = trimmed.match(
              /name:\s*['"](.*?)['"]|name:\s*(.+)/,
            );
            const taskName = nameMatch
              ? (nameMatch[1] || nameMatch[2] || "").trim()
              : `Task ${taskIndex + 1}`;

            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, "_").toLowerCase(),
              name: taskName,
              type: "default",
            };
            console.log("Started task (tasks format):", taskName);
          } else if (
            trimmed.startsWith("desc:") &&
            currentTask.name &&
            !inNestedLogic
          ) {
            // Update task name with description
            const descMatch = trimmed.match(
              /desc:\s*['"](.*?)['"]|desc:\s*(.+)/,
            );
            if (descMatch) {
              const description = (descMatch[1] || descMatch[2] || "")
                .trim()
                .replace(/^["']|["']$/g, "");
              // Use description as display name, keep original name as ID
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
              console.log("Updated task name to description:", description);
            }
          } else if (
            trimmed.startsWith("type:") &&
            currentTask.name &&
            !inNestedLogic
          ) {
            // Extract task type
            const typeMatch = trimmed.match(
              /type:\s*['"](.*?)['"]|type:\s*([^'"]+)/,
            );
            if (typeMatch) {
              currentTask.type = (typeMatch[1] || typeMatch[2] || "").trim();
              console.log("Set task type:", currentTask.type);
            }
          }

          // Reset nested logic flag if we're back to a lower indentation
          if (inNestedLogic && indent <= nestedLevel) {
            inNestedLogic = false;
            console.log(
              "Exited nested logic due to indentation change at line",
              i,
            );
          }
        }
      }

      // Add the last task
      if (currentTask.name) {
        tasks.push(currentTask as TaskNode);
        console.log("Saved final task:", currentTask.name);
      }

      console.log("PARSING COMPLETE");
      console.log("Total main workflow tasks found:", tasks.length);
      if (tasks.length > 0) {
        console.log("Task list:");
        tasks.forEach((task, i) =>
          console.log(
            `  ${i + 1}. ${task.name} (${task.type}) [id: ${task.id}]`,
          ),
        );
      } else {
        console.log("NO TASKS FOUND!");
      }

      return tasks;
    } catch (error) {
      console.error("Error parsing playbook content:", error);
      return [];
    }
  };

  const createFlowFromTasks = (tasks: TaskNode[]): { nodes: Node[], edges: Edge[] } => {
    const flowNodes: Node[] = [];
    const flowEdges: Edge[] = [];
    
    // Create nodes
    tasks.forEach((task, index) => {
      const nodeType = nodeTypes[task.type as keyof typeof nodeTypes] || nodeTypes.default;
      
      // Position nodes in a grid layout
      const x = (index % 3) * 300 + 100;
      const y = Math.floor(index / 3) * 150 + 100;
      
      flowNodes.push({
        id: task.id,
        type: 'default',
        position: { x, y },
        data: {
          label: (
            <div style={{ 
              padding: '12px 16px',
              borderRadius: '8px',
              background: 'white',
              border: `2px solid ${nodeType.color}`,
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
              minWidth: '160px',
              textAlign: 'center'
            }}>
              <div style={{ 
                fontSize: '20px', 
                marginBottom: '4px' 
              }}>
                {nodeType.icon}
              </div>
              <div style={{ 
                fontWeight: 'bold', 
                fontSize: '14px',
                color: '#262626',
                marginBottom: '4px'
              }}>
                {task.name}
              </div>
              <div style={{ 
                fontSize: '12px', 
                color: nodeType.color,
                textTransform: 'uppercase',
                fontWeight: '500'
              }}>
                {task.type}
              </div>
            </div>
          )
        },
        style: {
          background: 'transparent',
          border: 'none',
          padding: 0,
          width: 'auto',
          height: 'auto'
        }
      });
    });

    // Create edges based on dependencies
    tasks.forEach((task, index) => {
      if (task.dependencies && task.dependencies.length > 0) {
        task.dependencies.forEach(dep => {
          const sourceTask = tasks.find(t => t.name === dep);
          if (sourceTask) {
            flowEdges.push({
              id: `edge-${sourceTask.id}-${task.id}`,
              source: sourceTask.id,
              target: task.id,
              animated: true,
              style: { stroke: '#1890ff', strokeWidth: 2, strokeDasharray: '0' }
            });
          }
        });
      } else if (index > 0) {
        // If no explicit dependencies, connect to previous task
        flowEdges.push({
          id: `edge-${tasks[index - 1].id}-${task.id}`,
          source: tasks[index - 1].id,
          target: task.id,
          animated: true,
          style: { stroke: '#1890ff', strokeWidth: 2, strokeDasharray: '0' }
        });
      }
    });

    return { nodes: flowNodes, edges: flowEdges };
  };

  const loadPlaybookFlow = async () => {
    console.log("Loading playbook flow for ID:", playbookId || "editor");
    setLoading(true);

    try {
      let contentToUse = content; // Use provided content first

      // If no content provided and we have a playbook ID, fetch from API
      if (!contentToUse && playbookId) {
        console.log("Fetching content from API for ID:", playbookId);
        contentToUse = await apiService.getPlaybookContent(playbookId);
      }

      console.log("=== USING CONTENT ===");
      console.log(
        "Content source:",
        content ? "Provided directly" : "Fetched from API",
      );
      console.log("Content type:", typeof contentToUse);
      console.log("Content length:", contentToUse?.length || 0);
      console.log(
        "Content preview:",
        contentToUse?.substring(0, 200) || "No content",
      );
      if (contentToUse && contentToUse.trim()) {
        const parsedTasks = parsePlaybookContent(contentToUse);
        console.log("Parsed tasks from actual content:", parsedTasks);

        if (parsedTasks.length === 0) {
          console.log(
            "No tasks parsed from actual content - falling back to demo",
          );
          message.warning(
            "No workflow steps found in this playbook. Showing demo flow.",
          );

          // Create contextual demo based on playbook ID/name
          let demoTasks: EditableTaskNode[] = [];
          if (
            playbookId.toLowerCase().includes("weather") ||
            playbookName.toLowerCase().includes("weather")
          ) {
            demoTasks = [
              {
                id: "demo-1",
                name: "Fetch Weather Data",
                type: "http",
                enabled: true,
              },
              {
                id: "demo-2",
                name: "Process Weather Info",
                type: "script",
                enabled: true,
              },
              {
                id: "demo-3",
                name: "Generate Weather Report",
                type: "export",
                enabled: true,
              },
            ];
          } else if (
            playbookId.toLowerCase().includes("database") ||
            playbookId.toLowerCase().includes("sql")
          ) {
            demoTasks = [
              {
                id: "demo-1",
                name: "Connect to Database",
                type: "sql",
                enabled: true,
              },
              { id: "demo-2", name: "Query Data", type: "sql", enabled: true },
              {
                id: "demo-3",
                name: "Export Results",
                type: "export",
                enabled: true,
              },
            ];
          } else {
            demoTasks = [
              {
                id: "demo-1",
                name: "Initialize Process",
                type: "log",
                enabled: true,
              },
              {
                id: "demo-2",
                name: "Process Data",
                type: "script",
                enabled: true,
              },
              {
                id: "demo-3",
                name: "Export Results",
                type: "export",
                enabled: true,
              },
            ];
          }

          setTasks(demoTasks);
          const { nodes: flowNodes, edges: flowEdges } =
            createFlowFromTasks(demoTasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
        } else {
          console.log(
            "Successfully parsed tasks from actual content:",
            parsedTasks,
          );
          const editableTasks: EditableTaskNode[] = parsedTasks.map((task) => ({
            ...task,
            enabled: true,
          }));
          setTasks(editableTasks);
          const { nodes: flowNodes, edges: flowEdges } =
            createFlowFromTasks(editableTasks);
          console.log(
            "Created flow - nodes:",
            flowNodes.length,
            "edges:",
            flowEdges.length,
          );

          setNodes(flowNodes);
          setEdges(flowEdges);
          message.success(
            `Successfully parsed ${parsedTasks.length} workflow steps from ${playbookName}!`,
          );
        }
      } else {
        console.log("No content received from API");
        message.warning(`No content found for playbook: ${playbookName}`);

        // Show empty state or basic demo
        const demoTasks: EditableTaskNode[] = [
          {
            id: "empty-1",
            name: "No Content Available",
            type: "log",
            enabled: true,
          },
        ];
        setTasks(demoTasks);
        const { nodes: flowNodes, edges: flowEdges } =
          createFlowFromTasks(demoTasks);
        setNodes(flowNodes);
        setEdges(flowEdges);
      }
    } catch (error) {
      console.error("Error in loadPlaybookFlow:", error);
      message.error(
        `Failed to load playbook flow for ${playbookName}: ` +
        (error as Error).message,
      );

      // Show error demo
      const errorTasks: EditableTaskNode[] = [
        {
          id: "error-1",
          name: "Failed to Load Playbook",
          type: "log",
          enabled: true,
        },
        {
          id: "error-2",
          name: "Check API Connection",
          type: "script",
          enabled: true,
        },
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

  const handleFullscreen = () => {
    setFullscreen(!fullscreen);
  };

  return (
    <>
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
        bodyStyle={fullscreen ?
          { height: "85vh", padding: 0, overflow: "hidden" } :
          { height: "70vh", padding: 0, overflow: "hidden" }
        }
      >
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
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              nodeTypes={customNodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              attributionPosition="bottom-left"
              key={`flow-${tasks.length}-${tasks.map((t) => `${t.id}-${t.type}`).join("-")}`}
            >
              <Controls
                style={{
                  background: "white",
                  border: "1px solid #d9d9d9",
                  borderRadius: "8px",
                }}
              />
              <MiniMap
                nodeColor={(node) => {
                  const taskType = "default";
                  return (
                    nodeTypes[taskType as keyof typeof nodeTypes]?.color ||
                    nodeTypes.default.color
                  );
                }}
                style={{
                  background: "white",
                  border: "1px solid #d9d9d9",
                  borderRadius: "8px",
                }}
              />
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1}
                color="#f0f0f0"
              />
            </ReactFlow>
          )}
        </div>
      </Modal>
    </>
  );
};

export default FlowVisualization;
