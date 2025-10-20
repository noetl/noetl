import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';

interface LoopData {
    name?: string;
    scope?: string;
    overJSON?: string;
    [key: string]: unknown;
}

function LoopNode({ id, data }: NodeProps<Node<LoopData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'loop';
    const scope = data?.scope || '';
    const over = data?.overJSON || '';
    const overPreview = over ? (over.length > 42 ? over.slice(0, 39) + '…' : over) : '';
    return (
        <div style={{ padding: 8, border: '1px solid #faad14', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🔁 {name}</div>
            <input
                style={{ width: '100%', fontSize: 11, marginBottom: 4 }}
                value={scope}
                placeholder="scope"
                onChange={(e) => updateNodeData(id, { scope: e.target.value })}
                className="xy-theme__input"
            />
            <textarea
                style={{ width: '100%', fontSize: 10, fontFamily: 'monospace', marginBottom: 4 }}
                rows={3}
                value={over}
                placeholder="collection JSON"
                onChange={(e) => updateNodeData(id, { overJSON: e.target.value })}
                className="xy-theme__input"
            />
            {overPreview && <div style={{ fontSize: 10, opacity: 0.6 }}>{overPreview}</div>}
        </div>
    );
}

export default memo(LoopNode);
