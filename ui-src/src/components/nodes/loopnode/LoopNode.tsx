import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './LoopNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';

interface LoopData {
    name?: string;
    collection?: string;
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function LoopNodeInternal({ id, data = {} }: NodeProps<Node<LoopData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({ collection: '' });

    const openEditor = () => {
        setDraft({
            collection: data.collection || ''
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            collection: draft.collection
        });
        setModalOpen(false);
    };

    const summaryCollection = (() => {
        const c = (data.collection || '').trim();
        return !c ? '' : c.length < 30 ? c : c.slice(0, 27) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="LoopNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="LoopNode__header">
                <span className="LoopNode__header-text">🔁 {data.name || 'loop'}</span>
                <div className="LoopNode__header-buttons">
                    <Tooltip title="Edit Loop collection">
                        <Button
                            className="loop-edit-btn"
                            size="small"
                            type="text"
                            icon={<EditOutlined />}
                            onPointerDown={preventNodeDrag}
                            onMouseDown={preventNodeDrag}
                            onClick={(e) => { preventNodeDrag(e); openEditor(); }}
                        />
                    </Tooltip>
                    {!data.readOnly && data.onDelete && (
                        <Tooltip title="Delete node">
                            <Button
                                className="loop-delete-btn"
                                size="small"
                                type="text"
                                danger
                                icon={<DeleteOutlined />}
                                onPointerDown={preventNodeDrag}
                                onMouseDown={preventNodeDrag}
                                onClick={(e) => { preventNodeDrag(e); data.onDelete?.(id); }}
                            />
                        </Tooltip>
                    )}
                </div>
            </div>
            <div className="LoopNode__summary">
                {summaryCollection || <span className="LoopNode__empty-collection">(no collection)</span>}
            </div>
            <div className="LoopNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `Loop Config: ${data.name}` : 'Loop Config'}
                width={640}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="LoopNodeModal__container">
                    <div className="LoopNodeModal__section-title">Collection</div>
                    <Input
                        className="LoopNodeModal__collection"
                        value={draft.collection}
                        placeholder='{{ items }}'
                        onChange={e => setDraft(d => ({ ...d, collection: e.target.value }))}
                    />
                </div>
            </Modal>
        </div>
    );
}

export const LoopNode = memo(LoopNodeInternal);
