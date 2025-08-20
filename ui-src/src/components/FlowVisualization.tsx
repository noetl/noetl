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

// Custom styles to remove default ReactFlow node styling
const customNodeStyles = `
  .react-flow__node-default {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    box-shadow: none !important;
  }
  .react-flow__node-default .react-flow__node-main {
    background: transparent !important;
    border: none !important;
  }
`;

// Inject custom styles
const styleSheet = document.createElement("style");
styleSheet.innerText = customNodeStyles;
if (!document.head.querySelector('style[data-noetl-flow]')) {
  styleSheet.setAttribute('data-noetl-flow', 'true');
  document.head.appendChild(styleSheet);
}

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
}

const nodeTypes = {
  log: { color: '#52c41a', icon: '📝' },
  http: { color: '#1890ff', icon: '🌐' },
  sql: { color: '#722ed1', icon: '🗄️' },
  script: { color: '#fa8c16', icon: '⚙️' },
  secret: { color: '#eb2f96', icon: '🔑' },
  export: { color: '#13c2c2', icon: '📤' },
  python: { color: '#3776ab', icon: '🐍' },
  workbook: { color: '#ff6b35', icon: '📊' },
  default: { color: '#8c8c8c', icon: '📄' }
};

const FlowVisualization: React.FC<FlowVisualizationProps> = ({
  visible,
  onClose,
  playbookId,
  playbookName,
  content
}) => {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  const parsePlaybookContent = (content: string): TaskNode[] => {
    try {
      console.log('🔍 PARSING PLAYBOOK CONTENT');
      console.log('📏 Content length:', content.length);
      console.log('📖 Content preview (first 500 chars):');
      console.log(content.substring(0, 500));
      
      const lines = content.split('\n');
      console.log('📝 Total lines:', lines.length);
      
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
        if (i < 20 && (trimmed.includes('workflow') || trimmed.includes('step') || trimmed.includes('desc') || trimmed.includes('type') || trimmed.includes('tasks'))) {
          console.log(`📋 Line ${i}: [indent:${indent}] "${trimmed}"`);
        }
        
        // Look for workflow/tasks/steps section
        if (trimmed === 'workflow:' || trimmed.startsWith('workflow:') ||
            trimmed === 'tasks:' || trimmed.startsWith('tasks:') || 
            trimmed === 'steps:' || trimmed.startsWith('steps:')) {
          inWorkflowSection = true;
          workflowIndent = indent;
          console.log('🎯 Found workflow section at line', i, 'with indent', workflowIndent);
          continue;
        }

        if (inWorkflowSection) {
          // Check if we've left the workflow section
          if (trimmed && indent <= workflowIndent && !trimmed.startsWith('-') && trimmed.includes(':') && !trimmed.startsWith('#')) {
            console.log('🚪 Left workflow section at line', i, ':', trimmed);
            break;
          }
          
          // Detect nested logic sections (next:, then:, else:, when:)
          if (trimmed.match(/^(next|then|else|when):/)) {
            if (!inNestedLogic) {
              inNestedLogic = true;
              nestedLevel = indent;
              console.log('🔀 Entering nested logic at line', i, 'level', nestedLevel, ':', trimmed);
            }
            continue;
          }
          
          // If we're in nested logic, check if we're back to main workflow level
          if (inNestedLogic && indent === workflowIndent + 2 && trimmed.startsWith('- step:')) {
            inNestedLogic = false;
            console.log('🔙 Exiting nested logic at line', i);
          }
          
          // Process main workflow steps (not nested conditional steps)
          if (trimmed.startsWith('- step:') && !inNestedLogic && indent === workflowIndent + 2) {
            // Save previous task if exists
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
              console.log('💾 Saved main task:', currentTask.name);
            }
            
            // Extract step name
            const stepMatch = trimmed.match(/step:\s*([^'"]+)/);
            const taskName = stepMatch ? stepMatch[1].trim() : `Step ${taskIndex + 1}`;
            
            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase(),
              name: taskName,
              type: 'default'
            };
            console.log('✨ Started main task:', taskName, '[id:', currentTask.id, ']');
            
          } else if ((trimmed.startsWith('- name:') || (trimmed.startsWith('-') && trimmed.includes('name:'))) && !inNestedLogic) {
            // Handle tasks: format
            // Save previous task if exists
            if (currentTask.name) {
              tasks.push(currentTask as TaskNode);
              taskIndex++;
            }
            
            // Start new task
            const nameMatch = trimmed.match(/name:\s*['"](.*?)['"]|name:\s*(.+)/);
            const taskName = nameMatch ? (nameMatch[1] || nameMatch[2] || '').trim() : `Task ${taskIndex + 1}`;
            
            currentTask = {
              id: taskName.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase(),
              name: taskName,
              type: 'default'
            };
            console.log('✨ Started task (tasks format):', taskName);
            
          } else if (trimmed.startsWith('desc:') && currentTask.name && !inNestedLogic) {
            // Update task name with description
            const descMatch = trimmed.match(/desc:\s*['"](.*?)['"]|desc:\s*(.+)/);
            if (descMatch) {
              const description = (descMatch[1] || descMatch[2] || '').trim().replace(/^["']|["']$/g, '');
              // Use description as display name, keep original name as ID
              const originalName = currentTask.name;
              currentTask.name = description;
              if (!currentTask.id || currentTask.id === originalName.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase()) {
                currentTask.id = originalName.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase();
              }
              console.log('📝 Updated task name to description:', description);
            }
            
          } else if (trimmed.startsWith('type:') && currentTask.name && !inNestedLogic) {
            // Extract task type
            const typeMatch = trimmed.match(/type:\s*['"](.*?)['"]|type:\s*([^'"]+)/);
            if (typeMatch) {
              currentTask.type = (typeMatch[1] || typeMatch[2] || '').trim();
              console.log('🏷️ Set task type:', currentTask.type);
            }
          }
          
          // Reset nested logic flag if we're back to a lower indentation
          if (inNestedLogic && indent <= nestedLevel) {
            inNestedLogic = false;
            console.log('🔄 Exited nested logic due to indentation change at line', i);
          }
        }
      }

      // Add the last task
      if (currentTask.name) {
        tasks.push(currentTask as TaskNode);
        console.log('💾 Saved final task:', currentTask.name);
      }

      console.log('🎉 PARSING COMPLETE');
      console.log('📊 Total main workflow tasks found:', tasks.length);
      if (tasks.length > 0) {
        console.log('📋 Task list:');
        tasks.forEach((task, i) => console.log(`  ${i + 1}. ${task.name} (${task.type}) [id: ${task.id}]`));
      } else {
        console.log('❌ NO TASKS FOUND!');
      }
      
      return tasks;
    } catch (error) {
      console.error('💥 Error parsing playbook content:', error);
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
    console.log('Loading playbook flow for ID:', playbookId || 'editor');
    setLoading(true);
    
    try {
      let contentToUse = content; // Use provided content first
      
      // If no content provided and we have a playbook ID, fetch from API
      if (!contentToUse && playbookId) {
        console.log('Fetching content from API for ID:', playbookId);
        contentToUse = await apiService.getPlaybookContent(playbookId);
      }
      
      console.log('=== USING CONTENT ===');
      console.log('Content source:', content ? 'Provided directly' : 'Fetched from API');
      console.log('Content type:', typeof contentToUse);
      console.log('Content length:', contentToUse?.length || 0);
      console.log('Content preview:', contentToUse?.substring(0, 200) || 'No content');
      
      if (contentToUse && contentToUse.trim()) {
        const tasks = parsePlaybookContent(contentToUse);
        console.log('Parsed tasks from actual content:', tasks);
        
        if (tasks.length === 0) {
          console.log('❌ No tasks parsed from actual content - falling back to demo');
          message.warning('No workflow steps found in this playbook. Showing demo flow.');
          
          // Create contextual demo based on playbook ID/name
          let demoTasks: TaskNode[] = [];
          if (playbookId.toLowerCase().includes('weather') || playbookName.toLowerCase().includes('weather')) {
            demoTasks = [
              { id: 'demo-1', name: 'Fetch Weather Data', type: 'http' },
              { id: 'demo-2', name: 'Process Weather Info', type: 'script' },
              { id: 'demo-3', name: 'Generate Weather Report', type: 'export' }
            ];
          } else if (playbookId.toLowerCase().includes('database') || playbookId.toLowerCase().includes('sql')) {
            demoTasks = [
              { id: 'demo-1', name: 'Connect to Database', type: 'sql' },
              { id: 'demo-2', name: 'Query Data', type: 'sql' },
              { id: 'demo-3', name: 'Export Results', type: 'export' }
            ];
          } else {
            demoTasks = [
              { id: 'demo-1', name: 'Initialize Process', type: 'log' },
              { id: 'demo-2', name: 'Process Data', type: 'script' },
              { id: 'demo-3', name: 'Export Results', type: 'export' }
            ];
          }
          
          const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(demoTasks);
          setNodes(flowNodes);
          setEdges(flowEdges);
        } else {
          console.log('✅ Successfully parsed tasks from actual content:', tasks);
          const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(tasks);
          console.log('Created flow - nodes:', flowNodes.length, 'edges:', flowEdges.length);
          
          setNodes(flowNodes);
          setEdges(flowEdges);
          message.success(`Successfully parsed ${tasks.length} workflow steps from ${playbookName}!`);
        }
      } else {
        console.log('❌ No content received from API');
        message.warning(`No content found for playbook: ${playbookName}`);
        
        // Show empty state or basic demo
        const demoTasks: TaskNode[] = [
          { id: 'empty-1', name: 'No Content Available', type: 'log' }
        ];
        const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(demoTasks);
        setNodes(flowNodes);
        setEdges(flowEdges);
      }
    } catch (error) {
      console.error('❌ Error in loadPlaybookFlow:', error);
      message.error(`Failed to load playbook flow for ${playbookName}: ` + (error as Error).message);
      
      // Show error demo
      const errorTasks: TaskNode[] = [
        { id: 'error-1', name: 'Failed to Load Playbook', type: 'log' },
        { id: 'error-2', name: 'Check API Connection', type: 'script' }
      ];
      const { nodes: flowNodes, edges: flowEdges } = createFlowFromTasks(errorTasks);
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
      closable={false}
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
