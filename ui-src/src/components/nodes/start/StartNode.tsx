import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './StartNode.less';

function StartNode({ id, data }: NodeProps<Node<{ name?: string }>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'start';
    return (
        <div className="StartNode">
            <Handle type="source" position={Position.Right} />
            <div className="StartNode__title">▶️ {name}</div>
            <div className="StartNode__label">Start</div>
            <input
                className="xy-theme__input StartNode__input"
                value={name}
                onChange={(e) => updateNodeData(id, { name: e.target.value })}
                placeholder="start name"
            />
        </div>
    );
}

export default memo(StartNode);
