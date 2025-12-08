import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './LoopNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined, QuestionCircleOutlined } from '@ant-design/icons';
import { CodeEditor } from '../../CodeEditor';
import { NodeDocumentation } from '../NodeDocumentation';

interface LoopData {
    name?: string;
    collection?: string;
    task?: { name?: string; description?: string };
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function LoopNodeInternal({ id, data = {} }: NodeProps<Node<LoopData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [docsOpen, setDocsOpen] = useState(false);
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
                {summaryCollection || (data.task?.name ? <span className="LoopNode__description">{data.task.name}</span> : <span className="LoopNode__empty-collection">(no collection)</span>)}
            </div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `Loop Config: ${data.name}` : 'Loop Config'}
                width={640}
                footer={[
                    <Button
                        key="docs"
                        icon={<QuestionCircleOutlined />}
                        onClick={() => setDocsOpen(true)}
                        style={{ float: 'left' }}
                    >
                        Docs
                    </Button>,
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="LoopNodeModal__container">
                    <div className="LoopNodeModal__section-title">Collection</div>
                    <CodeEditor
                        value={draft.collection}
                        onChange={value => setDraft(d => ({ ...d, collection: value }))}
                        language="jinja2"
                        height={100}
                        placeholder='{{ items }}'
                    />
                </div>
            </Modal>

            <NodeDocumentation
                open={docsOpen}
                onClose={() => setDocsOpen(false)}
                nodeType="loop"
            />
        </div>
    );
}

export const LoopNode = memo(LoopNodeInternal);
