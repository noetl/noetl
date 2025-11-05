import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';

function EndNode({ id, data }: NodeProps<Node<{ name?: string }>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'end';
    return (
        <div style={{ padding: 8, border: '1px solid #ff4d4f', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="target" position={Position.Left} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>⛔ {name}</div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>End</div>
            <input
                style={{ marginTop: 6, width: '100%', fontSize: 11 }}
                value={name}
                onChange={(e) => updateNodeData(id, { name: e.target.value })}
                placeholder="end name"
                className="xy-theme__input"
            />
        </div>
    );
}

export default memo(EndNode);
