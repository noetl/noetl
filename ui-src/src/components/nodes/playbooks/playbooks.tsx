import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { NodeMeta, NodeComponentProps } from '../../nodeTypes';

function PlaybooksNode({ task, args }: NodeComponentProps) {
    const cfg = args || {};
    return (
        <div style={{ padding: 8, border: '1px solid #13c2c2', borderRadius: 8, fontSize: 12, background: '#fff', maxWidth: 220 }}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ fontWeight: 600, marginBottom: 4 }}>📚 {task.name || 'playbooks'}</div>
            {cfg.catalogPath && <div style={{ fontSize: 10, opacity: 0.8 }}>{cfg.catalogPath}</div>}
        </div>
    );
}
export default memo(PlaybooksNode);

export const playbooksMeta: NodeMeta = {
    type: 'playbooks',
    icon: '📘',
    label: 'Playbooks',
    color: '#13c2c2',
    description: 'Invoke sub-playbooks'
};
