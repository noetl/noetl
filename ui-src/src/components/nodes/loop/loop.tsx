import React from 'react';
import { Input, Select } from 'antd';
import { NodeTypeDef, NodeEditorProps } from '../../nodeTypes/NodeType';

const LoopEditor: React.FC<NodeEditorProps> = ({ task, readOnly, updateField }) => {
    const config = task.config || {};
    const setConfig = (k: string, v: any) => updateField('config', { ...config, [k]: v });

    return (
        <div className="node-editor loop-editor">
            <div className="flow-node-field">
                <span className="flow-node-field-label">Scope</span>
                <Select
                    className="flow-node-select nodrag"
                    value={config.scope || 'workbook'}
                    onChange={(v) => setConfig('scope', v)}
                    options={[{ value: 'workbook', label: 'Workbook' }, { value: 'playbook', label: 'Playbook' }]}
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">over: (JSON)</span>
                <Input.TextArea
                    className="xy-theme__input nodrag"
                    rows={4}
                    value={config.overJSON || ''}
                    onChange={(e) => setConfig('overJSON', e.target.value)}
                    placeholder='[1,2,3] or "$.items"'
                    disabled={!!readOnly}
                />
            </div>
        </div>
    );
};

export const loopNode: NodeTypeDef = {
    type: 'loop',
    label: 'Loop',
    icon: '🔁',
    color: '#faad14',
    description: 'Loop over workbook or playbook scope.',
    editor: LoopEditor,
};
