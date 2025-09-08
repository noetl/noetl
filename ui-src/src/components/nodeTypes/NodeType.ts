// NodeType.ts
// Defines the shape of a workflow node type and shared helpers

import { EditableTaskNode } from '../types';
import React from 'react';

export interface NodeEditorProps {
    task: EditableTaskNode;
    readOnly?: boolean;
    updateField: (field: keyof EditableTaskNode, value: any) => void;
}

export interface NodeTypeDef {
    type: string;           // unique id used in playbook/task (e.g. 'log')
    label: string;          // human friendly label (e.g. 'Log')
    icon: string;           // small emoji/icon shown in the UI
    color: string;          // accent color
    description?: string;   // optional description for future tooltips
    editor?: React.FC<NodeEditorProps>; // per-widget editor for unique inputs
    // In the future we can add: configSchema, formComponent, validator, etc.
}

export type NodeTypeMap = Record<string, NodeTypeDef>;
