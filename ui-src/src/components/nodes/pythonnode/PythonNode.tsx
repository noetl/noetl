import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PythonNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';

interface PythonData {
    name?: string;
    code?: string;
    module?: string;
    callable?: string;
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function PythonNodeInternal({ id, data = {} }: NodeProps<Node<PythonData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({
        code: '',
        module: '',
        callable: ''
    });

    const openEditor = () => {
        setDraft({
            code: data.code || '',
            module: data.module || '',
            callable: data.callable || ''
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            code: draft.code,
            module: draft.module,
            callable: draft.callable
        });
        setModalOpen(false);
    };

    const summaryCode = (() => {
        const c = (data.code || '').trim();
        return !c ? '' : c.length < 30 ? c : c.slice(0, 27) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="PythonNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="PythonNode__header">
                <span className="PythonNode__header-text">🐍 {data.name || 'python'}</span>
                <div className="PythonNode__header-buttons">
                    <Tooltip title="Edit Python code">
                        <Button
                            className="python-edit-btn"
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
                                className="python-delete-btn"
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
            <div className="PythonNode__summary">
                {summaryCode || <span className="PythonNode__empty-code">(no code)</span>}
            </div>
            <div className="PythonNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `Python Config: ${data.name}` : 'Python Config'}
                width={640}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit}>Save</Button>
                ]}
            >
                <div className="PythonNodeModal__container">
                    <div>
                        <div className="PythonNodeModal__section-title">Code</div>
                        <Input.TextArea
                            className="PythonNodeModal__code"
                            value={draft.code}
                            rows={10}
                            placeholder='def main(user_data):\n    return {"score": user_data["rating"] * 10}'
                            onChange={e => setDraft(d => ({ ...d, code: e.target.value }))}
                            style={{ fontFamily: 'monospace' }}
                        />
                    </div>
                    <div className="PythonNodeModal__section-title" style={{ marginTop: 16 }}>Or use module reference:</div>
                    <div>
                        <div className="PythonNodeModal__section-title">Module</div>
                        <Input
                            value={draft.module}
                            placeholder='scoring.calculator'
                            onChange={e => setDraft(d => ({ ...d, module: e.target.value }))}
                        />
                    </div>
                    <div>
                        <div className="PythonNodeModal__section-title">Callable</div>
                        <Input
                            value={draft.callable}
                            placeholder='compute_user_score'
                            onChange={e => setDraft(d => ({ ...d, callable: e.target.value }))}
                        />
                    </div>
                </div>
            </Modal>
        </div>
    );
}

export const PythonNode = memo(PythonNodeInternal);
