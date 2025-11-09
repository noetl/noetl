import { memo } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './LoopNode.less';

interface LoopData { name?: string; scope?: string; overJSON?: string;[key: string]: unknown; }

function LoopNodeInternal({ id, data }: NodeProps<Node<LoopData>>) {
    const { updateNodeData } = useReactFlow();
    const name = data?.name || 'loop';
    const scope = data?.scope || '';
    const over = data?.overJSON || '';
    const overPreview = over ? (over.length > 42 ? over.slice(0, 39) + '…' : over) : '';
    return (
        <div className="LoopNode">
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="LoopNode__title">🔁 {name}</div>
            <input
                className="xy-theme__input LoopNode__scope"
                value={scope}
                placeholder="scope"
                onChange={(e) => updateNodeData(id, { scope: e.target.value })}
            />
            <textarea
                className="xy-theme__input LoopNode__collection"
                rows={3}
                value={over}
                placeholder="collection JSON"
                onChange={(e) => updateNodeData(id, { overJSON: e.target.value })}
            />
            {overPreview && <div className="LoopNode__preview">{overPreview}</div>}
        </div>
    );
}

export const LoopNode = memo(LoopNodeInternal);
