import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeComponentProps, NodeMeta } from '../../nodeTypes';

function EndNodeRaw({ task }: NodeComponentProps) {
    return (
        <div style={{ padding: 8, border: '1px solid #ff4d4f', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="target" position={Position.Left} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>⛔ {task?.name || 'end'}</div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>End</div>
        </div>
    );
}
export default memo(EndNodeRaw);

export const endMeta: NodeMeta = {
    type: 'end',
    icon: '🏁',
    label: 'End',
    color: '#ff4d4f',
    description: 'Workflow end'
};
