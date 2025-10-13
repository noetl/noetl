import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeMeta, NodeComponentProps } from '../../nodeTypes';

function LoopNode({ task, args }: NodeComponentProps) {
    const cfg = args || {};
    return (
        <div style={{ padding: 8, border: '1px solid #faad14', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🔁 {task.name || 'loop'}</div>
            {cfg.scope && <div style={{ fontSize: 11 }}>scope: {cfg.scope}</div>}
            {cfg.overJSON && <div style={{ fontSize: 10, opacity: 0.7 }}>{cfg.overJSON.length > 42 ? cfg.overJSON.slice(0, 39) + '…' : cfg.overJSON}</div>}
        </div>
    );
}
export default memo(LoopNode);

export const loopMeta: NodeMeta = {
    type: 'loop',
    icon: '🔁',
    label: 'Loop',
    color: '#faad14',
    description: 'Iterate over a collection'
};
