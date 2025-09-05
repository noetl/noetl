import React, { useCallback, useState, useEffect, memo } from "react";
import {
  NodeProps,
  Handle,
  Position,

  useReactFlow,
} from "@xyflow/react";
import {
  Button,
  Select,
  Popconfirm,
} from "antd";
import {
  DeleteOutlined,
} from "@ant-design/icons";
import "@xyflow/react/dist/style.css";
import "../styles/FlowVisualization.css";
import { apiService } from "../services/api";
// Import modular node type definitions
import { nodeTypeMap, orderedNodeTypes } from './nodeTypes';
import { EditableTaskNode } from "./types";

// Custom editable node component (memoized) using React Flow updateNodeData pattern
export const EditableNode: React.FC<NodeProps> = memo(({ data, id, selected }) => {
  const { task, onEdit, onDelete, readOnly } = data as {
    task: EditableTaskNode;
    onEdit: (task: EditableTaskNode) => void;
    onDelete: (id: string) => void;
    readOnly?: boolean;
  };

  const { updateNodeData } = useReactFlow();
  const nodeType = nodeTypeMap[task?.type] || nodeTypeMap['default'];

  const updateField = (field: keyof EditableTaskNode, value: any) => {
    if (readOnly) return;
    const updatedTask = { ...task, [field]: value } as EditableTaskNode;
    // keep outer state in sync
    onEdit?.(updatedTask);
    // update node data for immediate React Flow re-render
    updateNodeData(id, { task: updatedTask });
  };

  const nodeClass = `EditableNode flow-node ${task?.type || 'default'} ${selected ? 'selected' : 'unselected'}`;

  return (
    <div className={nodeClass}>
      <Handle type="target" position={Position.Left} className="flow-node-handle flow-node-handle-target" />
      <Handle type="source" position={Position.Right} className="flow-node-handle flow-node-handle-source" />

      {selected && !readOnly && (
        // Toolbar with type selector and delete button
        <div className="EditableNode__toolbar flow-node-toolbar nodrag" onClick={(e) => e.stopPropagation()}>
          <Select
            value={task?.type || 'default'}
            onChange={(val) => updateField('type', val)}
            size="small"
            className="flow-node-type-select flow-node-toolbar-type-select"
            classNames={{
              popup: {
                root: "flow-node-type-dropdown"
              }
            }}
            popupMatchSelectWidth={false}
            getPopupContainer={() => document.body}
            options={orderedNodeTypes.map(t => ({ value: t, label: `${nodeTypeMap[t].icon} ${nodeTypeMap[t].label}` }))}
          />
          <Popconfirm
            title="Delete this component?"
            onConfirm={(e) => { e?.stopPropagation(); onDelete?.(id); }}
            okText="Yes"
            cancelText="No"
          >
            <Button size="small" danger icon={<DeleteOutlined />} className="flow-node-toolbar-button" onClick={(e) => e.stopPropagation()} />
          </Popconfirm>
        </div>
      )}

      <div className="flow-node-header">
        <span className="flow-node-icon" aria-hidden>{nodeType.icon}</span>
        <div className={`flow-node-status inline ${task?.type || 'default'}`}>{task?.type ? task.type.charAt(0).toUpperCase() + task.type.slice(1) : 'Default'}</div>
      </div>

      <div className="flow-node-name">
        <span className="flow-node-field-label">Name</span>
        <input
          value={task?.name ?? ''}
          onChange={(e) => updateField('name', e.target.value)}
          placeholder="Task name"
          className="xy-theme__input flow-node-name-input nodrag"
          disabled={!!readOnly}
          type="text"
        />
      </div>

      <div className="flow-node-description">
        <span className="flow-node-field-label">Description</span>
        <textarea
          value={task?.description || ''}
          onChange={(e) => updateField('description', e.target.value)}
          placeholder={readOnly ? '' : 'Description (optional)'}
          rows={2}
          className="xy-theme__input flow-node-description-input nodrag"
          disabled={!!readOnly}
        />
      </div>
    </div>
  );
});