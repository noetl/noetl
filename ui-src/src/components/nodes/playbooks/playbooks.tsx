import React from 'react';
import { Input } from 'antd';
import { NodeTypeDef, NodeEditorProps } from '../../nodeTypes/NodeType';

const PlaybooksEditor: React.FC<NodeEditorProps> = ({ task, readOnly, updateField }) => {
    const config = task.config || {};
    const setConfig = (k: string, v: any) => updateField('config', { ...config, [k]: v });

    return (
        <div className="node-editor playbooks-editor">
            <div className="flow-node-field">
                <span className="flow-node-field-label">Catalog Path</span>
                <Input
                    className="xy-theme__input nodrag"
                    value={config.catalogPath || ''}
                    onChange={(e) => setConfig('catalogPath', e.target.value)}
                    placeholder="/catalog/path"
                    disabled={!!readOnly}
                />
            </div>
            <div className="flow-node-field">
                <span className="flow-node-field-label">with: (JSON)</span>
                <Input.TextArea
                    className="xy-theme__input nodrag"
                    rows={4}
                    value={config.withJSON || ''}
                    onChange={(e) => setConfig('withJSON', e.target.value)}
                    placeholder='{"arg": "value"}'
                    disabled={!!readOnly}
                />
            </div>
        </div>
    );
};

export const playbooksNode: NodeTypeDef = {
    type: 'playbooks',
    label: 'Playbooks',
    icon: '📚',
    color: '#13c2c2',
    description: 'Execute playbooks under a catalog path.',
    editor: PlaybooksEditor,
};
