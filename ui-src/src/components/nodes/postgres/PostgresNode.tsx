import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PostgresNode.less';

interface PostgresData { name?: string; sql?: string;[key: string]: unknown; }

function PostgresNodeInternal({ id, data }: NodeProps<Node<PostgresData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'postgres';
    const sql = (data?.sql || '').toString();
    const preview = sql ? (sql.length > 46 ? sql.slice(0, 43) + '…' : sql) : '';
    return (
        <div className="PostgresNode">
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="PostgresNode__title">🐘 {name}</div>
            <textarea
                className="xy-theme__input PostgresNode__sql"
                rows={3}
                value={sql}
                placeholder="SELECT 1;"
                onChange={(e) => updateNodeData(id, { sql: e.target.value })}
            />
            {preview && <div className="PostgresNode__preview">{preview}</div>}
        </div>
    );
}

export const PostgresNode = memo(PostgresNodeInternal);
