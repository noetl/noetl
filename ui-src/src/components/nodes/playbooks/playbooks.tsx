import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';

interface PlaybooksData {
    name?: string;
    catalogPath?: string;
    [key: string]: unknown;
}

function PlaybooksNode({ id, data }: NodeProps<Node<PlaybooksData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'playbooks';
    const path = data?.catalogPath || '';
    return (
        <div style={{ padding: 8, border: '1px solid #13c2c2', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📚 {name}</div>
            <input
                style={{ width: '100%', fontSize: 11, marginBottom: 4 }}
                value={path}
                placeholder="catalog path"
                onChange={(e) => updateNodeData(id, { catalogPath: e.target.value })}
                className="xy-theme__input"
            />
            {path && <div style={{ fontSize: 10, opacity: 0.6 }}>{path}</div>}
        </div>
    );
}

export default memo(PlaybooksNode);
