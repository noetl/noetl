import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';

// Simplified Start node matching example snippet style
function StartNode({ id, data }: NodeProps<Node<{ name?: string }>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'start';

    return (
        <div style={{ padding: 8, border: '1px solid #3f8600', borderRadius: 8, fontSize: 12, background: '#fff' }}>
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>▶️ {name}</div>
            <div style={{ fontSize: 11, opacity: 0.7 }}>Start</div>
            <input
                style={{ marginTop: 6, width: '100%', fontSize: 11 }}
                value={name}
                onChange={(e) => updateNodeData(id, { name: e.target.value })}
                placeholder="start name"
                className="xy-theme__input"
            />
        </div>
    );
}

export default memo(StartNode);
