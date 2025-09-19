import React from 'react';
import { NodeTypeDef } from '../../nodeTypes/NodeType';

const StartEditor: React.FC = () => (
    <div className="node-editor start-editor">
        <div className="flow-node-field-label">Start node. No fields.</div>
    </div>
);

export const startNode: NodeTypeDef = {
    type: 'start',
    label: 'Start',
    icon: '▶️',
    color: '#3f8600',
    description: 'Entry point of a workflow.',
    editor: StartEditor as any,
};
