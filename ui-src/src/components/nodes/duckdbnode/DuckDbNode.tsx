import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './DuckDbNode.less';

interface DuckDbData { name?: string; sql?: string;[key: string]: unknown; }

function DuckDbNodeInternal({ id, data }: NodeProps<Node<DuckDbData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'duckdb';
    const sql = (data?.sql || '').toString();
    const preview = sql ? (sql.length > 46 ? sql.slice(0, 43) + '…' : sql) : '';
    return (
        <div className="DuckDbNode">
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="DuckDbNode__title">🦆 {name}</div>
            <textarea
                className="xy-theme__input DuckDbNode__sql"
                rows={3}
                value={sql}
                placeholder="SELECT 1;"
                onChange={(e) => updateNodeData(id, { sql: e.target.value })}
            />
            {preview && <div className="DuckDbNode__preview">{preview}</div>}
        </div>
    );
}

export const DuckDbNode = memo(DuckDbNodeInternal);
