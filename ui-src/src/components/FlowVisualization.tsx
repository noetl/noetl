import React, { useCallback, useState, useEffect } from 'react';
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
} from '@xyflow/react';
import { Modal, Button, Spin, message } from 'antd';
import { CloseOutlined, FullscreenOutlined } from '@ant-design/icons';
import '@xyflow/react/dist/style.css';
import { apiService } from '../services/api';

interface FlowVisualizationProps {
  visible: boolean;
  onClose: () => void;
  playbookId: string;
  playbookName: string;
}

interface TaskNode {
  id: string;
  name: string;
  type: string;
  config?: any;
  dependencies?: string[];
}

const nodeTypes = {
  log: { color: '#52c41a', icon: '📝' },
  http: { color: '#1890ff', icon: '🌐' },
  sql: { color: '#722ed1', icon: '🗄️' },
  script: { color: '#fa8c16', icon: '⚙️' },
  secret: { color: '#eb2f96', icon: '🔑' },
  export: { color: '#13c2c2', icon: '📤' },
  default: { color: '#8c8c8c', icon: '📄' }
};

const FlowVisualization: React.FC<FlowVisualizationProps> = ({
  visible,
  onClose,
  playbookId,
  playbookName
}) => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds: Edge[]) => addEdge(params, eds)),
    [setEdges]
  );

  const parsePlaybookContent = (content: string): TaskNode[] => {
    try {
      console.log('Parsing content:', content.substring(0, 500) + '...');
      
      // Simple YAML parsing for tasks
      const lines = content.split('\n');
      const tasks: TaskNode[] = [];
      let currentTask: Partial<TaskNode> = {};
      let inTasks = false;
      let taskIndex = 0;

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();
        
        // Look for tasks section
        if (trimmed === 'tasks:' || trimmed.startsWith('tasks:')) {
          inTasks = true;
          console.log('Found tasks section at line', i);
          continue;
        }

        if (inTasks) {
          // Start of a new task
          if (trimmed.startsWith('- name:') || (trimmed.startsWith('-') && trimmed.includes('name:'))) {
            // Save previous task if exists
            if (currentTask.name) {
              currentTask.id = currentTask.id || `task-${taskIndex + 1}`;
              tasks.push(currentTask as TaskNode);
              taskIndex++;
            }
            
            // Start new task
            const nameMatch = trimmed.match(/name:\s*['"](.*?)['"]|name:\s*(.+)/);
            const taskName = nameMatch ? (nameMatch[1] || nameMatch[2] || '').trim() : `Task ${taskIndex + 1}`;
            
            currentTask = {
              id: `task-${taskIndex + 1}`,
              name: taskName,
              type: 'default'
            };
            console.log('Found new task:', taskName);
            
          } else if (trimmed.startsWith('type:')) {
            // Extract task type
            const typeMatch = trimmed.match(/type:\s*['"](.*?)['"]|type:\s*(.+)/);
            if (typeMatch && currentTask) {
              currentTask.type = (typeMatch[1] || typeMatch[2] || '').trim();
              console.log('Set task type:', currentTask.type);
            }
            
          } else if (trimmed.startsWith('depends_on:') || trimmed.startsWith('dependsOn:')) {
            // Handle dependencies - could be array or single value
            const depsMatch = trimmed.match(/depends_on:\s*\[(.*?)\]|depends_on:\s*(.+)/);
            if (depsMatch && currentTask) {
              const depsStr = depsMatch[1] || depsMatch[2] || '';
              const deps = depsStr.split(',').map(d => d.replace(/['"]/g, '').trim()).filter(d => d);
              currentTask.dependencies = deps;
              console.log('Set dependencies:', deps);
            }
          }
          
          // If we hit a non-indented line that's not part of tasks, we're done
          if (trimmed && !trimmed.startsWith('-') && !trimmed.includes(':') && !line.startsWith(' ') && !line.startsWith('\t')) {
            break;
          }
        }
      }

      // Add the last task
      if (currentTask.name) {
        currentTask.id = currentTask.id || `task-${taskIndex + 1}`;
        tasks.push(currentTask as TaskNode);
      }

      console.log('Parsed tasks:', tasks);
      return tasks;
    } catch (error) {
      console.error('Error parsing playbook content:', error);
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
          border: 'none'
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
              style: { stroke: '#1890ff', strokeWidth: 2 }
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
          style: { stroke: '#1890ff', strokeWidth: 2 }
        });
      }
    });

    return { nodes: flowNodes, edges: flowEdges };
  };

  const loadPlaybookFlow = async () => {
    if (!playbookId) {
      console.log('No playbookId provided');
      return;
    }
    
    console.log('Loading playbook flow for ID:', playbookId);
    setLoading(true);
    try {
      const content = await apiService.getPlaybookContent(playbookId);
      console.log('Received content:', content);
      
      if (content) {
        const tasks = parsePlaybookContent(content);
        console.log('Parsed tasks:', tasks);
        
        if (tasks.length === 0) {
          // Create a simple demo flow if no tasks found
          const demoTasks: TaskNode[] = [
            {
              id: 'task-1',
              name: 'Start',
              type: 'log'
            },
            {
              id: 'task-2', 
              name: 'Process Data',
              type: 'script'
            },
            {
              id: 'task-3',
              name: 'Export Results',
              type: 'export'
            }
          ];
          const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(demoTasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
          message.info('No tasks found in playbook, showing demo flow');
        } else {
          const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(tasks);
          console.log('Created nodes:', flowNodes);
          console.log('Created edges:', flowEdges);
          
          setNodes(flowNodes);
          setEdges(flowEdges);
        }
      } else {
        message.warning('No playbook content found');
      }
    } catch (error) {
      console.error('Error loading playbook flow:', error);
      message.error('Failed to load playbook flow: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible && playbookId) {
      loadPlaybookFlow();
    }
  }, [visible, playbookId]);

  const handleFullscreen = () => {
    setFullscreen(!fullscreen);
  };

  return (
    <Modal
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '20px' }}>🔄</span>
          <span>Flow Visualization - {playbookName}</span>
        </div>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={fullscreen ? '95vw' : '80vw'}
      style={{ top: fullscreen ? 20 : 50 }}
      bodyStyle={{ 
        height: fullscreen ? '85vh' : '70vh', 
        padding: 0,
        overflow: 'hidden'
      }}
    >
      <div style={{
        position: 'absolute',
        right: 16,
        top: 16,
        zIndex: 1000,
        display: 'flex',
        gap: '8px'
      }}>
        <Button
          type="text"
          icon={<FullscreenOutlined />}
          onClick={handleFullscreen}
          title="Toggle Fullscreen"
          style={{ background: 'white', border: '1px solid #d9d9d9' }}
        />
        <Button
          type="text"
          icon={<CloseOutlined />}
          onClick={onClose}
          title="Close"
          style={{ background: 'white', border: '1px solid #d9d9d9' }}
        />
      </div>
      <div style={{ width: '100%', height: '100%', position: 'relative' }}>
        {loading ? (
          <div style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            height: '100%',
            flexDirection: 'column',
            gap: '16px'
          }}>
            <Spin size="large" />
            <div style={{ color: '#8c8c8c' }}>Loading playbook flow...</div>
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            attributionPosition="bottom-left"
          >
            <Controls 
              style={{
                background: 'white',
                border: '1px solid #d9d9d9',
                borderRadius: '8px'
              }}
            />
            <MiniMap 
              nodeColor={(node) => {
                // Extract task type from node data
                const taskType = 'default'; // Simplified for now
                return nodeTypes[taskType as keyof typeof nodeTypes]?.color || nodeTypes.default.color;
              }}
              style={{
                background: 'white',
                border: '1px solid #d9d9d9',
                borderRadius: '8px'
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
  );
};

export default FlowVisualization;
