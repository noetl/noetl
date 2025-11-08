import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './HttpNode.less';
import { Modal, Input, Select, Button, Tooltip } from 'antd';
import { EditOutlined } from '@ant-design/icons';

interface HttpData {
    name?: string;
    method?: string;
    url?: string;
    query?: string;
    headers?: Record<string, any>;
    body?: string;
    timeout?: number | string;
    [key: string]: unknown;
}

function HttpNode({ id, data = {} }: NodeProps<Node<HttpData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({ method: 'GET', url: '', query: '', headers: {}, body: '', timeout: '' as string | number });
    const [headerInput, setHeaderInput] = useState('');
    const [headerError, setHeaderError] = useState<string | null>(null);

    const serializeHeaders = (headers?: Record<string, any>) => {
        try {
            return headers && Object.keys(headers).length ? JSON.stringify(headers, null, 2) : '';
        } catch { return ''; }
    };

    const openEditor = () => {
        setDraft({
            method: (data.method || 'GET').toUpperCase(),
            url: data.url || '',
            query: data.query || '',
            headers: data.headers || {},
            body: data.body || '',
            timeout: data.timeout ?? '' as string | number,
        });
        setHeaderInput(serializeHeaders(data.headers));
        setHeaderError(null);
        setModalOpen(true);
    };

    const commit = () => {
        let headersObj = draft.headers;
        if (headerInput && !headerError) {
            try { headersObj = JSON.parse(headerInput); } catch { }
        }
        updateNodeData(id, {
            method: draft.method || 'GET',
            url: draft.url,
            query: draft.query,
            headers: headersObj,
            body: draft.body,
            timeout: draft.timeout === '' ? undefined : Number(draft.timeout)
        });
        setModalOpen(false);
    };

    const handleHeaderChange = (val: string) => {
        setHeaderInput(val);
        if (!val.trim()) {
            setHeaderError(null);
            setDraft(d => ({ ...d, headers: {} }));
            return;
        }
        try {
            const parsed = JSON.parse(val);
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                setHeaderError(null);
                setDraft(d => ({ ...d, headers: parsed }));
            } else {
                setHeaderError('Headers must be a JSON object');
            }
        } catch (e: any) {
            setHeaderError(e.message || 'Invalid JSON');
        }
    };

    const summaryUrl = (() => {
        const u = (data.url || '').trim();
        return !u ? '' : u.length < 34 ? u : u.slice(0, 31) + '…';
    })();

    const preventNodeDrag = (e: React.MouseEvent | React.PointerEvent) => {
        (window as any).__skipNextNodeModal = true;
        e.preventDefault();
        e.stopPropagation();
    };

    return (
        <div className="HttpNode" onDoubleClick={openEditor}>
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div className="HttpNode__header">
                <span className="HttpNode__header-text">🌐 {data.name || 'http'}</span>
                <Tooltip title="Edit HTTP config">
                    <Button
                        className="http-edit-btn"
                        size="small"
                        type="text"
                        icon={<EditOutlined />}
                        onPointerDown={preventNodeDrag}
                        onMouseDown={preventNodeDrag}
                        onClick={(e) => { preventNodeDrag(e); openEditor(); }}
                    />
                </Tooltip>
            </div>
            <div className="HttpNode__summary">
                {summaryUrl || <span className="HttpNode__empty-url">(no url)</span>}
            </div>
            <div className="HttpNode__method">{(data.method || 'GET').toUpperCase()}</div>
            <div className="HttpNode__hint">double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data.name ? `HTTP Config: ${data.name}` : 'HTTP Config'}
                width={640}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit} disabled={!!headerError}>Save</Button>
                ]}
            >
                <div className="HttpNodeModal__container">
                    <div className="HttpNodeModal__row">
                        <Select
                            className="HttpNodeModal__select"
                            value={draft.method}
                            onChange={(v) => setDraft(d => ({ ...d, method: v }))}
                            options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].map(m => ({ value: m, label: m }))}
                        />
                        <Input
                            value={draft.url}
                            placeholder="https://api.example.com"
                            onChange={e => setDraft(d => ({ ...d, url: e.target.value }))}
                        />
                    </div>
                    <Input
                        value={draft.query}
                        placeholder="query string (?k=v&k2=v2) or custom"
                        onChange={e => setDraft(d => ({ ...d, query: e.target.value }))}
                    />
                    <div>
                        <div className="HttpNodeModal__section-title">Headers (JSON object)</div>
                        <Input.TextArea
                            className="HttpNodeModal__headers"
                            value={headerInput}
                            rows={4}
                            placeholder='{"Authorization":"Bearer ..."}'
                            onChange={e => handleHeaderChange(e.target.value)}
                        />
                        {headerError && <div className="HttpNodeModal__error">{headerError}</div>}
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Body (raw / JSON)</div>
                        <Input.TextArea
                            className="HttpNodeModal__body"
                            value={draft.body}
                            rows={5}
                            placeholder='{"key":"value"} or raw text'
                            onChange={e => setDraft(d => ({ ...d, body: e.target.value }))}
                        />
                    </div>
                    <div className="HttpNodeModal__timeout-row">
                        <Input
                            className="HttpNodeModal__timeout-input"
                            type="number"
                            value={draft.timeout}
                            placeholder="timeout ms"
                            onChange={e => setDraft(d => ({ ...d, timeout: e.target.value }))}
                        />
                        <div className="HttpNodeModal__timeout-hint">Leave blank for default</div>
                    </div>
                </div>
            </Modal>
        </div>
    );
}

export default memo(HttpNode);
