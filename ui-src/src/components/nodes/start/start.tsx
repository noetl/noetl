import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeComponentProps, NodeMeta } from '../../nodeTypes';

function StartNodeRaw({ task }: NodeComponentProps) {
    return (
        <div style={{ padding: 8, border: '1px solid #3f8600', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>▶️ {task?.name || 'start'}</div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>Start</div>
        </div>
    );
}

export default memo(StartNodeRaw);

export const startMeta: NodeMeta = {
    type: 'start',
    icon: '🚀',
    label: 'Start',
    color: '#3f8600',
    description: 'Workflow entry point'
};
