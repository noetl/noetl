import React, { memo } from "react";
import { NodeProps, Handle, Position } from "@xyflow/react";
import { EditableTaskNode } from "./types";
import { nodeTypeMap } from './nodeTypes';
import "@xyflow/react/dist/style.css";
import "../styles/FlowVisualization.css";

// Simplified node: just visual summary. Editing now happens in a popup modal managed by parent.
export const EditableNode: React.FC<NodeProps> = memo(({ data, id, selected }) => {
  const { task, readOnly } = data as {
    task: EditableTaskNode;
    onEdit: (task: EditableTaskNode) => void; // kept for backward compatibility
    onDelete: (id: string) => void;          // not used directly here now
    readOnly?: boolean;
  };

  const nodeType = nodeTypeMap[task?.type] || ({
    type: task?.type || 'unknown',
    label: 'Unknown',
    icon: '❓',
    color: '#8c8c8c',
    description: 'Unknown node type',
  } as any);

  const nodeClass = `EditableNode flow-node minimal ${task?.type || 'unknown'} ${selected ? 'selected' : 'unselected'}`;

  return (
    <div className={nodeClass} data-node-id={id}>
      <Handle type="target" position={Position.Left} className="flow-node-handle flow-node-handle-target" />
      <Handle type="source" position={Position.Right} className="flow-node-handle flow-node-handle-source" />
      <div className="flow-node-header compact" title={task?.name || task?.type}>
        <span className="flow-node-icon" aria-hidden>{(nodeType as any).icon}</span>
        <div className={`flow-node-status inline ${task?.type || 'unknown'}`}>{task?.name || task?.type}</div>
      </div>
      {/* No inline editor content anymore */}
    </div>
  );
});