import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';

interface PythonData { name?: string; module?: string; code?: string;[key: string]: unknown; }

function PythonNode({ id, data }: NodeProps<Node<PythonData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'python';
    const module = data?.module || '';
    const hasCode = !!data?.code;
    return (
        <div style={{ padding: 8, border: '1px solid #3776ab', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🐍 {name}</div>
            <input
                style={{ marginBottom: 4, width: '100%', fontSize: 11 }}
                value={module}
                placeholder="module path"
                onChange={(e) => updateNodeData(id, { module: e.target.value })}
                className="xy-theme__input"
            />
            {hasCode && <div style={{ fontSize: 10, opacity: 0.7 }}>inline code</div>}
        </div>
    );
}

export default memo(PythonNode);
