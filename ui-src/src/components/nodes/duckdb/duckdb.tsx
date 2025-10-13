import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeMeta, NodeComponentProps } from '../../nodeTypes';

function DuckDbNode({ task, args }: NodeComponentProps) {
    const cfg = args || {};
    const sqlPreview = (cfg.sql || '').toString();
    return (
        <div style={{ padding: 8, border: '1px solid #8c61ff', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🦆 {task.name || 'duckdb'}</div>
            {sqlPreview && <div style={{ fontSize: 10, opacity: 0.8 }}>{sqlPreview.length > 46 ? sqlPreview.slice(0, 43) + '…' : sqlPreview}</div>}
        </div>
    );
}
export default memo(DuckDbNode);

export const duckdbMeta: NodeMeta = {
    type: 'duckdb',
    icon: '🦆',
    label: 'DuckDB',
    color: '#8c61ff',
    description: 'Run DuckDB SQL'
};
