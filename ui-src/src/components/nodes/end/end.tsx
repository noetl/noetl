import React from 'react';
import { NodeTypeDef } from '../../nodeTypes/NodeType';

const EndEditor: React.FC = () => (
    <div className="node-editor end-editor">
    </div>
);

export const endNode: NodeTypeDef = {
    type: 'end',
    label: 'End',
    icon: '⛔',
    color: '#ff4d4f',
    description: 'Terminal step with no next.',
    editor: EndEditor as any,
};
