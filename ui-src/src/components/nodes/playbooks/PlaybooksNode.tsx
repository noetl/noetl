import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PlaybooksNode.less';

interface PlaybooksData { name?: string; catalogPath?: string;[key: string]: unknown; }

function PlaybooksNode({ id, data }: NodeProps<Node<PlaybooksData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'playbooks';
    const path = data?.catalogPath || '';
    return (
        <div className="PlaybooksNode">
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="PlaybooksNode__title">📚 {name}</div>
            <input
                className="xy-theme__input PlaybooksNode__input"
                value={path}
                placeholder="catalog path"
                onChange={(e) => updateNodeData(id, { catalogPath: e.target.value })}
            />
            {path && <div className="PlaybooksNode__path">{path}</div>}
        </div>
    );
}

export default memo(PlaybooksNode);
