import { memo, useState } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import './HttpNode.less';
import { Modal, Input, Select, Button, Tooltip } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';

interface HttpData {
    name?: string;
    method?: string;
    endpoint?: string;
    headers?: Record<string, any>;
    params?: Record<string, any>;
    payload?: Record<string, any>;
    onDelete?: (taskId: string) => void;
    readOnly?: boolean;
    [key: string]: unknown;
}

function HttpNodeInternal({ id, data = {} }: NodeProps<Node<HttpData>>) {
    const { updateNodeData } = useReactFlow();
    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState({
        method: 'GET',
        endpoint: '',
        headers: {} as Record<string, any>,
        params: {} as Record<string, any>,
        payload: {} as Record<string, any>
    });
    const [headerInput, setHeaderInput] = useState('');
    const [paramsInput, setParamsInput] = useState('');
    const [payloadInput, setPayloadInput] = useState('');
    const [headerError, setHeaderError] = useState<string | null>(null);
    const [paramsError, setParamsError] = useState<string | null>(null);
    const [payloadError, setPayloadError] = useState<string | null>(null);

    const serializeObject = (obj?: Record<string, any>) => {
        try {
            return obj && Object.keys(obj).length ? JSON.stringify(obj, null, 2) : '';
        } catch { return ''; }
    };

    const openEditor = () => {
        setDraft({
            method: (data.method || 'GET').toUpperCase(),
            endpoint: data.endpoint || '',
            headers: data.headers || {},
            params: data.params || {},
            payload: data.payload || {},
        });
        setHeaderInput(serializeObject(data.headers));
        setParamsInput(serializeObject(data.params));
        setPayloadInput(serializeObject(data.payload));
        setHeaderError(null);
        setParamsError(null);
        setPayloadError(null);
        setModalOpen(true);
    };

    const commit = () => {
        let headersObj = draft.headers;
        let paramsObj = draft.params;
        let payloadObj = draft.payload;

        if (headerInput && !headerError) {
            try { headersObj = JSON.parse(headerInput); } catch { }
        }
        if (paramsInput && !paramsError) {
            try { paramsObj = JSON.parse(paramsInput); } catch { }
        }
        if (payloadInput && !payloadError) {
            try { payloadObj = JSON.parse(payloadInput); } catch { }
        }

        updateNodeData(id, {
            method: draft.method || 'GET',
            endpoint: draft.endpoint,
            headers: headersObj,
            params: paramsObj,
            payload: payloadObj
        });
        setModalOpen(false);
    };

    const handleJSONChange = (val: string, field: 'headers' | 'params' | 'payload') => {
        const setInput = field === 'headers' ? setHeaderInput : field === 'params' ? setParamsInput : setPayloadInput;
        const setError = field === 'headers' ? setHeaderError : field === 'params' ? setParamsError : setPayloadError;

        setInput(val);
        if (!val.trim()) {
            setError(null);
            setDraft(d => ({ ...d, [field]: {} }));
            return;
        }
        try {
            const parsed = JSON.parse(val);
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                setError(null);
                setDraft(d => ({ ...d, [field]: parsed }));
            } else {
                setError(`${field} must be a JSON object`);
            }
        } catch (e: any) {
            setError(e.message || 'Invalid JSON');
        }
    };

    const summaryEndpoint = (() => {
        const u = (data.endpoint || '').trim();
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
                <div className="HttpNode__header-buttons">
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
                    {!data.readOnly && data.onDelete && (
                        <Tooltip title="Delete node">
                            <Button
                                className="http-delete-btn"
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
            <div className="HttpNode__summary">
                {summaryEndpoint || <span className="HttpNode__empty-url">(no endpoint)</span>}
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
                    <Button key="save" type="primary" onClick={commit} disabled={!!(headerError || paramsError || payloadError)}>Save</Button>
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
                            value={draft.endpoint}
                            placeholder='{{ api }}/users/{{ user_id }}'
                            onChange={e => setDraft(d => ({ ...d, endpoint: e.target.value }))}
                        />
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Headers (JSON object)</div>
                        <Input.TextArea
                            className="HttpNodeModal__headers"
                            value={headerInput}
                            rows={4}
                            placeholder='{"Authorization": "Bearer {{ token }}"}'
                            onChange={e => handleJSONChange(e.target.value, 'headers')}
                        />
                        {headerError && <div className="HttpNodeModal__error">{headerError}</div>}
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Params (JSON object)</div>
                        <Input.TextArea
                            className="HttpNodeModal__params"
                            value={paramsInput}
                            rows={3}
                            placeholder='{"limit": 10}'
                            onChange={e => handleJSONChange(e.target.value, 'params')}
                        />
                        {paramsError && <div className="HttpNodeModal__error">{paramsError}</div>}
                    </div>
                    <div>
                        <div className="HttpNodeModal__section-title">Payload (JSON object)</div>
                        <Input.TextArea
                            className="HttpNodeModal__payload"
                            value={payloadInput}
                            rows={4}
                            placeholder='{"query": "{{ search_term }}"}'
                            onChange={e => handleJSONChange(e.target.value, 'payload')}
                        />
                        {payloadError && <div className="HttpNodeModal__error">{payloadError}</div>}
                    </div>
                </div>
            </Modal>
        </div>
    );
}

export const HttpNode = memo(HttpNodeInternal);
