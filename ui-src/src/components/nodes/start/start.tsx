import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeTypeDef } from '../../nodeTypes/NodeType';

function StartNode({ data }: any) {
    const task = data?.task || {};
    return (
        <div style={{ padding: 8, border: '1px solid #3f8600', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>▶️ {task.name || 'start'}</div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>Start</div>
        </div>
    );
}

const MemoizedStartNode = memo(StartNode);

export const startNode: NodeTypeDef = {
    type: 'start',
    label: 'Start',
    icon: '▶️',
    color: '#3f8600',
    description: 'Entry point of a workflow.',
    editor: MemoizedStartNode as any,
};

export default MemoizedStartNode;
