import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

function PlaybooksNode({ data }: any) {
    const task = data?.task || {};
    const cfg = task.config || {};
    return (
        <div style={{ padding: 8, border: '1px solid #13c2c2', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📚 {task.name || 'playbooks'}</div>
            {cfg.catalogPath && <div style={{ fontSize: 10, opacity: 0.8 }}>{cfg.catalogPath}</div>}
        </div>
    );
}
export default memo(PlaybooksNode);
