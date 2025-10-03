import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

function HttpNode({ data }: any) {
    const task = data?.task || {};
    const cfg = task.config || {};
    return (
        <div style={{ padding: 8, border: '1px solid #1890ff', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🌐 {task.name || 'http'}</div>
            {cfg.url && <div style={{ fontSize: 11, wordBreak: 'break-all' }}>{cfg.url}</div>}
            {cfg.method && <div style={{ fontSize: 10, opacity: 0.7 }}>{cfg.method}</div>}
        </div>
    );
}
export default memo(HttpNode);
