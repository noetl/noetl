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
import { Modal, Button, Spin, message, Select, Space, Popconfirm, Tag } from "antd";
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
import MonacoEditor from '@monaco-editor/react';
// @ts-ignore - types may not be present
import yaml from 'js-yaml'; // NEW: robust YAML parsing

interface FlowVisualizationProps {
  visible: boolean;
  onClose: () => void;
  playbookId: string;
  playbookName: string;
  content?: string; // Optional content to use instead of fetching from API
  readOnly?: boolean; // NEW: render in read-only (view) mode
  hideTitle?: boolean; // NEW: suppress internal title (avoid duplicates)
  onUpdateContent?: (newContent: string) => void; // NEW: callback to push updated YAML back to editor
}



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
  // Modal/editor state
  const [activeTask, setActiveTask] = useState<EditableTaskNode | null>(null);
  const [editorTab, setEditorTab] = useState<'config' | 'code' | 'json' | 'raw'>('config');

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
      setNodes((currentNodes) => currentNodes.map((node) => {
        if (node.id === updatedTask.id) {
          const existingTask: EditableTaskNode = (node.data as any)?.task || { id: updatedTask.id, name: '', type: 'workbook' };
          const merged: EditableTaskNode = { ...existingTask, ...updatedTask, id: existingTask.id };
          return { ...node, data: { ...node.data, task: merged } } as any;
        }
        return node;
      }));
      setHasChanges(true);
      setActiveTask((prev) => prev && prev.id === updatedTask.id ? { ...prev, ...updatedTask, id: prev.id } : prev); // keep modal in sync
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
            readOnly,
            onOpen: () => setActiveTask(task),
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

  // Helper: escape double quotes in strings
  const esc = (s: string) => (s || "").replace(/"/g, '\\"');

  // Helper: build task/workflow YAML blocks
  const buildWorkflowYaml = (taskList: EditableTaskNode[], rootKey: 'workflow' | 'tasks'): string => {
    const lines: string[] = [`${rootKey}:`];

    const isPlainObject = (v: any) => Object.prototype.toString.call(v) === '[object Object]';
    const serializeConfig = (cfg: any, indent: string) => {
      Object.entries(cfg).forEach(([k, v]) => {
        if (v === undefined || v === null) return;
        if (k === 'code' || k === 'sql') return; // handled separately
        if (isPlainObject(v)) {
          lines.push(`${indent}${k}:`);
          serializeConfig(v, indent + '  ');
        } else if (Array.isArray(v)) {
          lines.push(`${indent}${k}:`);
          v.forEach(item => {
            if (isPlainObject(item)) {
              lines.push(`${indent}  -`);
              Object.entries(item).forEach(([ik, iv]) => {
                lines.push(`${indent}    ${ik}: ${JSON.stringify(iv)}`);
              });
            } else {
              lines.push(`${indent}  - ${JSON.stringify(item)}`);
            }
          });
        } else if (typeof v === 'string') {
          // quote if contains special chars
          if (/[#:>-]|^\s|\s$|"/.test(v)) {
            lines.push(`${indent}${k}: ${JSON.stringify(v)}`);
          } else {
            lines.push(`${indent}${k}: "${v}"`);
          }
        } else {
          lines.push(`${indent}${k}: ${JSON.stringify(v)}`);
        }
      });
    };

    taskList.forEach((t) => {
      const displayNameRaw = t.name ?? '';
      const displayName = displayNameRaw.trim();
      if (!displayName) {
        return; // skip incomplete edits
      }
      const sanitizedStep = displayName.replace(/[^a-zA-Z0-9_-]/g, '_');
      const cfg = (t as any).config || {};
      const hasOtherConfigKeys = cfg && Object.keys(cfg).some(k => !['code', 'sql'].includes(k));
      if (rootKey === 'workflow') {
        lines.push(`  - step: ${sanitizedStep}`);
        if (t.description) {
          lines.push(`    desc: "${esc(t.description)}"`);
        } else if (displayName !== sanitizedStep) {
          lines.push(`    desc: "${esc(displayName)}"`);
        }
        if (t.type && !['workbook'].includes(t.type)) {
          lines.push(`    type: ${t.type}`);
        }
        if (hasOtherConfigKeys) {
          lines.push(`    config:`);
          serializeConfig(cfg, '      ');
        }
        if (cfg.code) {
          lines.push(`    code: |`);
          cfg.code.split(/\r?\n/).forEach((l: string) => lines.push(`      ${l}`));
        }
        if (cfg.sql) {
          lines.push(`    sql: |`);
          cfg.sql.split(/\r?\n/).forEach((l: string) => lines.push(`      ${l}`));
        }
      } else { // tasks style
        lines.push(`  - name: "${esc(displayName)}"`);
        if (t.type && !['workbook'].includes(t.type)) {
          lines.push(`    type: ${t.type}`);
        }
        if (t.description) {
          lines.push(`    desc: "${esc(t.description)}"`);
        }
        if (hasOtherConfigKeys) {
          lines.push(`    config:`);
          serializeConfig(cfg, '      ');
        }
        if (cfg.code) {
          lines.push(`    code: |`);
          cfg.code.split(/\r?\n/).forEach((l: string) => lines.push(`      ${l}`));
        }
        if (cfg.sql) {
          lines.push(`    sql: |`);
          cfg.sql.split(/\r?\n/).forEach((l: string) => lines.push(`      ${l}`));
        }
      }
    });
    return lines.join('\n');
  };

  // Helper: find top-level block range (start, end) for a given key
  const findBlockRange = (lines: string[], key: string): [number, number] | null => {
    const start = lines.findIndex(l => l.trim() === `${key}:`);
    if (start === -1) return null;
    let end = lines.length;
    for (let i = start + 1; i < lines.length; i++) {
      const raw = lines[i];
      if (!raw.trim()) continue;
      if (/^[A-Za-z0-9_-]+:\s*$/.test(raw) && !/^\s/.test(raw)) { // new top-level key line
        end = i;
        break;
      }
    }
    return [start, end];
  };

  // Replace existing tasks/workflow section (prefer tasks if present) and remove duplicates
  const updateWorkflowInYaml = (original: string, taskList: EditableTaskNode[]): string => {
    if (!original || !original.trim()) {
      return buildWorkflowYaml(taskList, 'workflow');
    }
    const lines = original.split(/\r?\n/);
    const tasksRange = findBlockRange(lines, 'tasks');
    const workflowRange = findBlockRange(lines, 'workflow');

    // Decide which root key to use
    const useKey: 'tasks' | 'workflow' = tasksRange ? 'tasks' : 'workflow';

    // Collect ranges to remove (all existing tasks/workflow blocks)
    const ranges: Array<[number, number]> = [];
    if (tasksRange) ranges.push(tasksRange);
    if (workflowRange) ranges.push(workflowRange);

    // Sort ranges by start
    ranges.sort((a, b) => a[0] - b[0]);

    // Build new block
    const newBlock = buildWorkflowYaml(taskList, useKey);

    // If no existing block, append
    if (ranges.length === 0) {
      const needsBlank = lines.length > 0 && lines[lines.length - 1].trim() !== '';
      return [...lines, needsBlank ? '' : '', newBlock].join('\n');
    }

    // Remove from end to start to avoid index shifts
    let mutable = [...lines];
    for (let i = ranges.length - 1; i >= 0; i--) {
      const [s, e] = ranges[i];
      mutable.splice(s, e - s);
    }

    // Insert new block at position of first removed range start
    const insertAt = ranges[0][0];
    const before = mutable.slice(0, insertAt);
    const after = mutable.slice(insertAt);

    // Ensure blank line separation
    if (before.length && before[before.length - 1].trim() !== '') before.push('');
    if (after.length && after[0].trim() !== '') after.unshift('');

    return [...before, newBlock, ...after].join('\n');
  };

  // Save entire workflow (now also updates YAML content)
  const handleSaveWorkflow = useCallback(async () => {
    try {
      setLoading(true);
      const updatedYaml = updateWorkflowInYaml(content || '', tasks);
      if (onUpdateContent) onUpdateContent(updatedYaml);

      // Attempt backend persistence directly (so user doesn't need to click main Save)
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

  // Legacy line-based parser kept as fallback
  const legacyParsePlaybookContent = (content: string): TaskNode[] => {
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
            const stepMatch = trimmed.match(/step:\s*([^'"#]+)/);
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
                .replace(/^['"]|['"]$/g, "");
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
              /type:\s*['"](.*?)['"]|type:\s*([^'"#]+)/
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
    } catch {
      return [];
    }
  };

  // New js-yaml based parser
  const parsePlaybookContent = (content: string): TaskNode[] => {
    try {
      const doc: any = yaml.load(content);
      if (!doc || typeof doc !== 'object') return [];
      const sequence = Array.isArray(doc.tasks)
        ? doc.tasks
        : Array.isArray(doc.workflow)
          ? doc.workflow
          : [];
      if (!Array.isArray(sequence)) return [];
      const parsed: TaskNode[] = [];
      sequence.forEach((entry: any, idx: number) => {
        if (!entry || typeof entry !== 'object') return;
        let rawName: string = entry.name || entry.step || entry.desc || `Task ${idx + 1}`;
        if (typeof rawName !== 'string') rawName = `Task ${idx + 1}`;
        const idBase = rawName.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase() || `task_${idx + 1}`;
        let id = idBase;
        let dupe = 1;
        while (parsed.some(t => t.id === id)) id = `${idBase}_${dupe++}`;
        const t: any = {
          id,
          name: rawName,
          type: mapType(entry.type || 'workbook'),
        };
        if (entry.config && typeof entry.config === 'object') {
          t.config = { ...entry.config };
        }
        if (entry.code && typeof entry.code === 'string') {
          t.config = t.config || {}; t.config.code = entry.code;
        }
        if (entry.sql && typeof entry.sql === 'string') {
          t.config = t.config || {}; t.config.sql = entry.sql;
        }
        parsed.push(t as TaskNode);
      });
      return parsed.length ? parsed : [];
    } catch (e) {
      console.warn('YAML parse failed, falling back to legacy parser', e);
      return legacyParsePlaybookContent(content);
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
                nodes={nodes.map(n => ({
                  ...n,
                  data: { ...n.data, readOnly },
                }))}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={(e, node) => {
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
  return <>
    {flowInner}
    <Modal
      open={!!activeTask}
      onCancel={() => setActiveTask(null)}
      onOk={() => setActiveTask(null)}
      width={900}
      title={activeTask ? `Edit: ${activeTask.name}` : ''}
      okText="Close"
      cancelButtonProps={{ style: { display: 'none' } }}
    >
      {activeTask && (
        <div className="node-modal-body">
          <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
            <Select
              disabled={!!readOnly}
              value={activeTask.type}
              onChange={(val) => handleEditTask({ ...activeTask, type: val })}
              options={orderedNodeTypes.map(t => ({ value: t, label: `${nodeTypeMap[t].icon} ${nodeTypeMap[t].label}` }))}
              style={{ width: 180 }}
            />
            <Select
              value={editorTab}
              onChange={(v) => setEditorTab(v as any)}
              options={[
                { value: 'config', label: 'Config Fields' },
                { value: 'code', label: 'Code' },
                { value: 'json', label: 'Config JSON' },
                { value: 'raw', label: 'Raw Task' },
              ]}
              style={{ width: 160 }}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <input
              disabled={!!readOnly}
              value={activeTask.name}
              onChange={(e) => handleEditTask({ ...activeTask, name: e.target.value })}
              placeholder="Step name"
              className="xy-theme__input"
              style={{ width: '100%', padding: '6px 8px' }}
            />
          </div>
          {editorTab === 'config' && (() => {
            const nodeDef = nodeTypeMap[activeTask.type] || nodeTypeMap['workbook'] || { editor: null, label: activeTask.type } as any;
            const EditorComp = (nodeDef as any)?.editor;
            if (!EditorComp) return <div style={{ padding: 8 }}>No editor UI for type: <code>{activeTask.type}</code></div>;
            const updateField = (field: keyof EditableTaskNode, value: any) => handleEditTask({ ...activeTask, [field]: value });
            return <EditorComp task={activeTask} readOnly={readOnly} updateField={updateField} />;
          })()}
          {editorTab === 'code' && (
            <div style={{ height: 300 }}>
              <MonacoEditor
                height="300px"
                defaultLanguage={activeTask.type === 'python' ? 'python' : (activeTask.type === 'duckdb' || activeTask.type === 'postgres') ? 'sql' : 'javascript'}
                value={(activeTask.config?.code) || activeTask.config?.sql || ''}
                onChange={(val) => {
                  if (readOnly) return;
                  const cfg = { ...(activeTask.config || {}) } as any;
                  if (activeTask.type === 'python') cfg.code = val || '';
                  if (activeTask.type === 'duckdb' || activeTask.type === 'postgres') cfg.sql = val || '';
                  handleEditTask({ ...activeTask, config: cfg });
                }}
                theme="vs-dark"
                options={{ minimap: { enabled: false }, fontSize: 13 }}
              />
            </div>
          )}
          {editorTab === 'json' && (
            <div style={{ height: 300 }}>
              <MonacoEditor
                height="300px"
                defaultLanguage="json"
                value={JSON.stringify(activeTask.config || {}, null, 2)}
                onChange={(val) => {
                  if (readOnly) return;
                  try {
                    const parsed = JSON.parse(val || '{}');
                    handleEditTask({ ...activeTask, config: parsed });
                  } catch { }
                }}
                theme="vs-dark"
                options={{ minimap: { enabled: false }, fontSize: 13 }}
              />
            </div>
          )}
          {editorTab === 'raw' && (
            <div style={{ height: 300 }}>
              <MonacoEditor
                height="300px"
                defaultLanguage="json"
                value={JSON.stringify(activeTask, null, 2)}
                onChange={(val) => {
                  if (readOnly) return;
                  try {
                    const parsed = JSON.parse(val || '{}');
                    handleEditTask({ ...(parsed as any), id: activeTask.id });
                  } catch { }
                }}
                theme="vs-dark"
                options={{ minimap: { enabled: false }, fontSize: 13 }}
              />
            </div>
          )}
        </div>
      )}
    </Modal>
  </>;
};

export default FlowVisualization;
