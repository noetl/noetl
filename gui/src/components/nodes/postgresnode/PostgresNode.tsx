import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PostgresNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined } from '@ant-design/icons';

interface PostgresData {
    name?: string;
    query?: string;
    [key: string]: unknown;
}

function PostgresNodeInternal({ id, data = {} }: NodeProps<Node<PostgresData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({ query: '' });

    const openEditor = () => {
        setDraft({
            query: data.query || ''
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            query: draft.query
        });
        setModalOpen(false);
    };

    const summaryQuery = (() => {
        const q = (data.query || '').trim();
        return !q ? '' : q.length < 30 ? q : q.slice(0, 27) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="PostgresNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="PostgresNode__header">
                <span className="PostgresNode__header-text">🐘 {data.name || 'postgres'}</span>
                <Tooltip title="Edit Postgres query">
                    <Button
                        className="postgres-edit-btn"
                        size="small"
                        type="text"
                        icon={<EditOutlined />}
                        onPointerDown={preventNodeDrag}
                        onMouseDown={preventNodeDrag}
                        onClick={(e) => { preventNodeDrag(e); openEditor(); }}
                    />
                </Tooltip>
            </div>
            <div className="PostgresNode__summary">
                {summaryQuery || <span className="PostgresNode__empty-query">(no query)</span>}
            </div>
            <div className="PostgresNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `Postgres Config: ${data.name}` : 'Postgres Config'}
                width={640}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="PostgresNodeModal__container">
                    <div className="PostgresNodeModal__section-title">Query</div>
                    <Input.TextArea
                        className="PostgresNodeModal__query"
                        value={draft.query}
                        rows={12}
                        placeholder='SELECT * FROM users WHERE active = true'
                        onChange={e => setDraft(d => ({ ...d, query: e.target.value }))}
                        style={{ fontFamily: 'monospace' }}
                    />
                </div>
            </Modal>
        </div>
    );
}

export const PostgresNode = memo(PostgresNodeInternal);
