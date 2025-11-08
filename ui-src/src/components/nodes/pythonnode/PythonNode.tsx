import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PythonNode.less';

interface PythonData { name?: string; module?: string; code?: string;[key: string]: unknown; }

function PythonNodeInternal({ id, data }: NodeProps<Node<PythonData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'python';
    const module = data?.module || '';
    const hasCode = !!data?.code;
    return (
        <div className="PythonNode">
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="PythonNode__title">🐍 {name}</div>
            <input
                className="xy-theme__input PythonNode__module"
                value={module}
                placeholder="module path"
                onChange={(e) => updateNodeData(id, { module: e.target.value })}
            />
            {hasCode && <div className="PythonNode__code-flag">inline code</div>}
        </div>
    );
}

export const PythonNode = memo(PythonNodeInternal);
