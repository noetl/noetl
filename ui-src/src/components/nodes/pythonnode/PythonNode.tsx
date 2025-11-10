import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './PythonNode.less';
import { Modal, Input, Button, Tooltip } from 'antd';
import { EditOutlined } from '@ant-design/icons';

interface PythonData {
    name?: string;
    code?: string;
    [key: string]: unknown;
}

function PythonNodeInternal({ id, data = {} }: NodeProps<Node<PythonData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({ code: '' });

    const openEditor = () => {
        setDraft({
            code: data.code || ''
        });
        setModalOpen(true);
    };

    const commit = () => {
        updateNodeData(id, {
            code: draft.code
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
                    <div className="PythonNodeModal__section-title">Code</div>
                    <Input.TextArea
                        className="PythonNodeModal__code"
                        value={draft.code}
                        rows={15}
                        placeholder='def main(data):\n    # Transform data\n    return data'
                        onChange={e => setDraft(d => ({ ...d, code: e.target.value }))}
                        style={{ fontFamily: 'monospace' }}
                    />
                </div>
            </Modal>
        </div>
    );
}

export const PythonNode = memo(PythonNodeInternal);
