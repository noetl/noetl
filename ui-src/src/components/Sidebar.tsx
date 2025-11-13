import React from 'react';
import { useDnD } from './DnDContext';
import '../styles/Sidebar.css';

const nodeMeta: Record<string, { icon: string; color: string; label: string }> = {
    start: { icon: '🚀', color: '#2563eb', label: 'Start' },
    http: { icon: '🌐', color: '#9333ea', label: 'HTTP' },
    python: { icon: '🐍', color: '#15803d', label: 'Python' },
    postgres: { icon: '🐘', color: '#1d4ed8', label: 'Postgres' },
    duckdb: { icon: '🦆', color: '#0d9488', label: 'DuckDB' },
    playbooks: { icon: '📘', color: '#4b5563', label: 'Playbook' },
    workbook: { icon: '📊', color: '#ff6b35', label: 'Workbook' },
    loop: { icon: '🔁', color: '#a16207', label: 'Loop' },
    end: { icon: '🏁', color: '#dc2626', label: 'End' },
};

const Sidebar: React.FC = () => {
    const [_, setType] = useDnD();

    const onDragStart = (event: React.DragEvent, nodeType: string) => {
        setType(nodeType);
        event.dataTransfer.effectAllowed = 'move';
    };

    return (
        <aside className="workflow-sidebar">
            <div className="sidebar-header">
                <h3>Components</h3>
                <p className="sidebar-description">Drag components to the canvas</p>
            </div>
            <div className="sidebar-nodes">
                {Object.entries(nodeMeta).map(([type, meta]) => (
                    <div
                        key={type}
                        className="dndnode"
                        style={{ borderColor: meta.color }}
                        onDragStart={(event) => onDragStart(event, type)}
                        draggable
                    >
                        <span className="node-icon">{meta.icon}</span>
                        <span className="node-label">{meta.label}</span>
                    </div>
                ))}
            </div>
        </aside>
    );
};

export default Sidebar;
