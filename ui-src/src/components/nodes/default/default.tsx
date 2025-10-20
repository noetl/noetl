import React from 'react';

// Default node component with all details rendered directly
const DefaultEditor: React.FC = () => (
    <div
        className="node-editor default-editor"
        data-node-type="default"
        data-node-label="Default"
        data-node-icon="📄"
        data-node-color="#8c8c8c"
        data-node-description="Generic task with no specific type."
    >
        <div className="flow-node-field-label">📄 Default widget. No specific fields.</div>
    </div>
);

export default DefaultEditor;
