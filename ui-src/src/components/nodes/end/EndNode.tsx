import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './EndNode.less';

function EndNode({ id, data }: NodeProps<Node<{ name?: string }>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'end';
    return (
        <div className="EndNode">
            <Handle type="target" position={Position.Left} />
            <div className="EndNode__title">⛔ {name}</div>
            <div className="EndNode__label">End</div>
            <input
                className="xy-theme__input EndNode__input"
                value={name}
                onChange={(e) => updateNodeData(id, { name: e.target.value })}
                placeholder="end name"
            />
        </div>
    );
}

export default memo(EndNode);
