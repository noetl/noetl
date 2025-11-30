import React, { useState } from 'react';
import { useDnD } from './DnDContext';
import '../styles/Sidebar.css';

interface NodeMeta {
    icon: string;
    color: string;
    label: string;
    description: string;
    category: 'flow' | 'data' | 'logic' | 'actions';
}

const nodeMeta: Record<string, NodeMeta> = {
    start: {
        icon: '🚀',
        color: '#2563eb',
        label: 'Start',
        description: 'Workflow entry point',
        category: 'flow'
    },
    end: {
        icon: '🏁',
        color: '#dc2626',
        label: 'End',
        description: 'Workflow completion',
        category: 'flow'
    },
    loop: {
        icon: '🔁',
        color: '#a16207',
        label: 'Loop',
        description: 'Iterate over collections',
        category: 'logic'
    },
    http: {
        icon: '🌐',
        color: '#9333ea',
        label: 'HTTP',
        description: 'API requests',
        category: 'actions'
    },
    python: {
        icon: '🐍',
        color: '#15803d',
        label: 'Python',
        description: 'Execute Python code',
        category: 'actions'
    },
    postgres: {
        icon: '🐘',
        color: '#1d4ed8',
        label: 'Postgres',
        description: 'Database queries',
        category: 'data'
    },
    duckdb: {
        icon: '🦆',
        color: '#0d9488',
        label: 'DuckDB',
        description: 'Analytics queries',
        category: 'data'
    },
    workbook: {
        icon: '📊',
        color: '#ff6b35',
        label: 'Workbook',
        description: 'Reusable task',
        category: 'logic'
    },
    playbooks: {
        icon: '📘',
        color: '#4b5563',
        label: 'Playbook',
        description: 'Nested playbook',
        category: 'logic'
    },
};

const categories = {
    flow: { label: 'Flow Control', icon: '⚡' },
    data: { label: 'Data Sources', icon: '💾' },
    logic: { label: 'Logic & Tasks', icon: '🧩' },
    actions: { label: 'Actions', icon: '⚙️' }
};

const Sidebar: React.FC = () => {
    const [_, setType] = useDnD();
    const [draggedType, setDraggedType] = useState<string | null>(null);
    const [expandedCategories, setExpandedCategories] = useState<Record<string, boolean>>({
        flow: true,
        data: true,
        logic: true,
        actions: true
    });

    const onDragStart = (event: React.DragEvent, nodeType: string) => {
        setType(nodeType);
        setDraggedType(nodeType);
        event.dataTransfer.effectAllowed = 'move';

        // Add ghost image styling
        const target = event.currentTarget as HTMLElement;
        target.style.opacity = '0.5';
    };

    const onDragEnd = (event: React.DragEvent) => {
        setDraggedType(null);
        const target = event.currentTarget as HTMLElement;
        target.style.opacity = '1';
    };

    const toggleCategory = (category: string) => {
        setExpandedCategories(prev => ({
            ...prev,
            [category]: !prev[category]
        }));
    };

    const groupedNodes = Object.entries(nodeMeta).reduce((acc, [type, meta]) => {
        if (!acc[meta.category]) {
            acc[meta.category] = [];
        }
        acc[meta.category].push({ type, ...meta });
        return acc;
    }, {} as Record<string, Array<{ type: string } & NodeMeta>>);

    return (
        <aside className="workflow-sidebar">
            <div className="sidebar-header">
                <div className="sidebar-header-content">
                    <h3 className="sidebar-title">
                        <span className="sidebar-title-icon">🎨</span>
                        Node Library
                    </h3>
                    <p className="sidebar-subtitle">Drag & drop to build your workflow</p>
                </div>
            </div>

            <div className="sidebar-content">
                {Object.entries(categories).map(([categoryKey, categoryInfo]) => {
                    const nodes = groupedNodes[categoryKey] || [];
                    const isExpanded = expandedCategories[categoryKey];

                    return (
                        <div key={categoryKey} className="sidebar-category">
                            <button
                                className="sidebar-category-header"
                                onClick={() => toggleCategory(categoryKey)}
                            >
                                <span className="category-icon">{categoryInfo.icon}</span>
                                <span className="category-label">{categoryInfo.label}</span>
                                <span className={`category-toggle ${isExpanded ? 'expanded' : ''}`}>
                                    ▼
                                </span>
                            </button>

                            {isExpanded && (
                                <div className="sidebar-category-nodes">
                                    {nodes.map(({ type, icon, color, label, description }) => (
                                        <div
                                            key={type}
                                            className={`dndnode ${draggedType === type ? 'dragging' : ''}`}
                                            style={{
                                                '--node-color': color,
                                                '--node-color-light': `${color}15`,
                                                '--node-color-hover': `${color}25`
                                            } as React.CSSProperties}
                                            onDragStart={(event) => onDragStart(event, type)}
                                            onDragEnd={onDragEnd}
                                            draggable
                                        >
                                            <div className="dndnode-icon-wrapper">
                                                <span className="dndnode-icon">{icon}</span>
                                            </div>
                                            <div className="dndnode-content">
                                                <span className="dndnode-label">{label}</span>
                                                <span className="dndnode-description">{description}</span>
                                            </div>
                                            <div className="dndnode-drag-indicator">
                                                <svg width="8" height="14" viewBox="0 0 8 14" fill="currentColor">
                                                    <circle cx="2" cy="2" r="1.5" />
                                                    <circle cx="6" cy="2" r="1.5" />
                                                    <circle cx="2" cy="7" r="1.5" />
                                                    <circle cx="6" cy="7" r="1.5" />
                                                    <circle cx="2" cy="12" r="1.5" />
                                                    <circle cx="6" cy="12" r="1.5" />
                                                </svg>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </aside>
    );
};

export default Sidebar;
