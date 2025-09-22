import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

function EndNode({ data }: any) {
    const task = data?.task || {};
    return (
        <div style={{ padding: 8, border: '1px solid #ff4d4f', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="target" position={Position.Left} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>⛔ {task.name || 'end'}</div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>End</div>
        </div>
    );
}
export default memo(EndNode);
