import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './EndNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined } from '@ant-design/icons';

function EndNodeInternal({ id, data = {} }: NodeProps<Node<{ name?: string }>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({ name: '' });

    const openEditor = () => {
        setDraft({
            name: data.name || 'end'
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            name: draft.name
        });
        setModalOpen(false);
    };

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="EndNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <div className="EndNode__header">
                <span className="EndNode__header-text">🏁 {data.name || 'end'}</span>
                <Tooltip title="Edit End node">
                    <Button
                        className="end-edit-btn"
                        size="small"
                        type="text"
                        icon={<EditOutlined />}
                        onPointerDown={preventNodeDrag}
                        onMouseDown={preventNodeDrag}
                        onClick={(e) => { preventNodeDrag(e); openEditor(); }}
                    />
                </Tooltip>
            </div>
            <div className="EndNode__label">End</div>
            <div className="EndNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title="End Node Config"
                width={480}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="EndNodeModal__container">
                    <div className="EndNodeModal__section-title">Name</div>
                    <Input
                        className="EndNodeModal__name"
                        value={draft.name}
                        placeholder='end'
                        onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
                    />
                </div>
            </Modal>
        </div>
    );
}

export const EndNode = memo(EndNodeInternal);
