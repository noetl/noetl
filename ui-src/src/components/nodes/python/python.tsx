import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

function PythonNode({ data }: any) {
    const task = data?.task || {};
    const cfg = task.config || {};
    return (
        <div style={{ padding: 8, border: '1px solid #3776ab', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🐍 {task.name || 'python'}</div>
            {cfg.module && <div style={{ fontSize: 11 }}>{cfg.module}</div>}
            {cfg.code && <div style={{ fontSize: 10, opacity: 0.7 }}>inline code</div>}
        </div>
    );
}
export default memo(PythonNode);
