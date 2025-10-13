import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeMeta, NodeComponentProps } from '../../nodeTypes';

function PostgresNode({ task, args }: NodeComponentProps) {
    const cfg = args || {};
    const sqlPreview = (cfg.sql || '').toString();
    return (
        <div style={{ padding: 8, border: '1px solid #336791', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🐘 {task.name || 'postgres'}</div>
            {sqlPreview && <div style={{ fontSize: 10, opacity: 0.8 }}>{sqlPreview.length > 46 ? sqlPreview.slice(0, 43) + '…' : sqlPreview}</div>}
        </div>
    );
}
export default memo(PostgresNode);

export const postgresMeta: NodeMeta = {
    type: 'postgres',
    icon: '🐘',
    label: 'Postgres',
    color: '#336791',
    description: 'Run Postgres SQL'
};
