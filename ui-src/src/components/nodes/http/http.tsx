import { memo, useState, useEffect, useCallback } from 'react';
import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import { Modal, Input, Select, Button, Tooltip } from 'antd';
import { EditOutlined } from '@ant-design/icons';

interface HttpConfigDraft {
    method: string;
    url: string;
    query: string;
    headers: Record<string, any>;
    body: string;
    timeout: string | number | '';
}

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

function HttpNode({ id, data }: NodeProps<Node<HttpData>>) {
    const { updateNodeData } = useReactFlow();
    const cfg = data || {};

    const [modalOpen, setModalOpen] = useState(false);
    const [draft, setDraft] = useState<HttpConfigDraft>(() => ({
        method: (cfg.method || 'GET').toUpperCase(),
        url: cfg.url || '',
        query: cfg.query || '',
        headers: cfg.headers || {},
        body: cfg.body || '',
        timeout: cfg.timeout ?? ''
    }));
    const [headerInput, setHeaderInput] = useState<string>(() => {
        try { return draft.headers && Object.keys(draft.headers).length ? JSON.stringify(draft.headers, null, 2) : ''; } catch { return ''; }
    });
    const [headerError, setHeaderError] = useState<string | null>(null);

    // Re-sync draft when task updates externally (after save elsewhere)
    useEffect(() => {
        const newCfg = data || {};
        setDraft({
            method: (newCfg.method || 'GET').toUpperCase(),
            url: newCfg.url || '',
            query: newCfg.query || '',
            headers: newCfg.headers || {},
            body: newCfg.body || '',
            timeout: newCfg.timeout ?? ''
        });
        try { setHeaderInput(newCfg.headers && Object.keys(newCfg.headers).length ? JSON.stringify(newCfg.headers, null, 2) : ''); } catch { setHeaderInput(''); }
    }, [data]);

    const openEditor = useCallback(() => {
        // fresh copy each open
        const current = data || {};
        setDraft({
            method: (current.method || 'GET').toUpperCase(),
            url: current.url || '',
            query: current.query || '',
            headers: current.headers || {},
            body: current.body || '',
            timeout: current.timeout ?? ''
        });
        try { setHeaderInput(current.headers && Object.keys(current.headers).length ? JSON.stringify(current.headers, null, 2) : ''); } catch { setHeaderInput(''); }
        setHeaderError(null);
        setModalOpen(true);
    }, [data]);

    const commit = useCallback(() => {
        let headersObj: Record<string, any> = draft.headers || {};
        if (headerInput && !headerError) {
            try { headersObj = JSON.parse(headerInput); } catch { /* ignore; keep previous */ }
        }
        updateNodeData(id, {
            method: draft.method || 'GET',
            url: draft.url || '',
            query: draft.query || '',
            headers: headersObj,
            body: draft.body || '',
            timeout: draft.timeout === '' ? undefined : Number(draft.timeout)
        });
        setModalOpen(false);
    }, [draft, headerInput, headerError, id, updateNodeData]);

    const handleHeaderChange = (val: string) => {
        setHeaderInput(val);
        if (!val.trim()) { setHeaderError(null); setDraft(d => ({ ...d, headers: {} })); return; }
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

    const summaryUrl: string = (() => {
        const u = (data?.url || '').trim();
        if (!u) return '';
        if (u.length < 34) return u;
        return u.slice(0, 31) + '…';
    })();

    return (
        <div
            style={{ padding: 8, border: '1px solid #1890ff', borderRadius: 8, fontSize: 12, background: '#fff', width: 240, cursor: 'pointer' }}
            onDoubleClick={openEditor}
        >
            <Handle type="target" position={Position.Left} />
            <Handle type="source" position={Position.Right} />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontWeight: 600, marginBottom: 4 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>🌐 {data?.name || 'http'}</span>
                <Tooltip title="Edit HTTP config">
                    <Button
                        className="http-edit-btn"
                        size="small"
                        type="text"
                        icon={<EditOutlined style={{ fontSize: 14 }} />}
                        onPointerDown={(e) => { (window as any).__skipNextNodeModal = true; e.stopPropagation(); }}
                        onMouseDown={(e) => { (window as any).__skipNextNodeModal = true; e.stopPropagation(); }}
                        onClick={(e) => { (window as any).__skipNextNodeModal = true; e.preventDefault(); e.stopPropagation(); openEditor(); }}
                    />
                </Tooltip>
            </div>
            <div style={{ fontSize: 11, wordBreak: 'break-all', lineHeight: 1.3 }}>
                {summaryUrl || <span style={{ opacity: 0.5 }}>(no url)</span>}
            </div>
            <div style={{ fontSize: 10, opacity: 0.7, marginTop: 2 }}>{(data?.method || 'GET').toUpperCase()}</div>
            <div style={{ fontSize: 9, opacity: 0.55, marginTop: 4 }}>double-click or edit icon</div>

            <Modal
                open={modalOpen}
                onCancel={() => setModalOpen(false)}
                title={data?.name ? `HTTP Config: ${data?.name}` : 'HTTP Config'}
                width={640}
                footer={[
                    <Button key="cancel" onClick={() => setModalOpen(false)}>Cancel</Button>,
                    <Button key="save" type="primary" onClick={commit} disabled={!!headerError}>Save</Button>
                ]}
            >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <Select

                            value={draft.method}
                            onChange={(v) => setDraft(d => ({ ...d, method: v }))}
                            style={{ width: 120 }}
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
                        <div style={{ fontSize: 11, fontWeight: 500, marginBottom: 4 }}>Headers (JSON object)</div>
                        <Input.TextArea

                            value={headerInput}
                            rows={4}
                            placeholder='{"Authorization":"Bearer ..."}'
                            onChange={e => handleHeaderChange(e.target.value)}
                            style={{ fontFamily: 'monospace' }}
                        />
                        {headerError && <div style={{ color: '#dc2626', fontSize: 11, marginTop: 4 }}>{headerError}</div>}
                    </div>
                    <div>
                        <div style={{ fontSize: 11, fontWeight: 500, marginBottom: 4 }}>Body (raw / JSON)</div>
                        <Input.TextArea

                            value={draft.body}
                            rows={5}
                            placeholder='{"key":"value"} or raw text'
                            onChange={e => setDraft(d => ({ ...d, body: e.target.value }))}
                            style={{ fontFamily: 'monospace' }}
                        />
                    </div>
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                        <Input

                            type="number"
                            value={draft.timeout}
                            placeholder="timeout ms"
                            onChange={e => setDraft(d => ({ ...d, timeout: e.target.value }))}
                            style={{ width: 140 }}
                        />
                        <div style={{ fontSize: 11, opacity: 0.65 }}>Leave blank for default</div>
                    </div>

                </div>
            </Modal>
        </div>
    );
}

export default memo(HttpNode);
