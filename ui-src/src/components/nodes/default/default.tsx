import React from 'react';
import { NodeTypeDef } from '../../nodeTypes';

const DefaultEditor: React.FC = () => (
    <div className="node-editor default-editor">
        <div className="flow-node-field-label">Default widget. No specific fields.</div>
    </div>
);

export const defaultNode: NodeTypeDef = {
    type: 'default',
    label: 'Default',
    icon: '📄',
    color: '#8c8c8c',
    description: 'Generic task with no specific type.',
    editor: DefaultEditor as any,
};
