import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';

interface DuckDbData { name?: string; sql?: string;[key: string]: unknown; }

function DuckDbNode({ id, data }: NodeProps<Node<DuckDbData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'duckdb';
    const sql = (data?.sql || '').toString();
    const preview = sql ? (sql.length > 46 ? sql.slice(0, 43) + '…' : sql) : '';
    return (
        <div style={{ padding: 8, border: '1px solid #8c61ff', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🦆 {name}</div>
            <textarea
                style={{ width: '100%', fontSize: 10, fontFamily: 'monospace', marginBottom: 4 }}
                rows={3}
                value={sql}
                placeholder="SELECT 1;"
                onChange={(e) => updateNodeData(id, { sql: e.target.value })}
                className="xy-theme__input"
            />
            {preview && <div style={{ fontSize: 10, opacity: 0.6 }}>{preview}</div>}
        </div>
    );
}

export default memo(DuckDbNode);
