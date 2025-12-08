import React from 'react';
import MonacoEditor from '@monaco-editor/react';

interface CodeEditorProps {
    value: string;
    onChange: (value: string) => void;
    language?: 'python' | 'sql' | 'json' | 'yaml' | 'jinja2' | 'plaintext';
    height?: number | string;
    placeholder?: string;
    readOnly?: boolean;
    theme?: 'light' | 'vs-dark';
    minimap?: boolean;
}

/**
 * Reusable code editor component for node inputs
 * Uses Monaco Editor with syntax highlighting and code intelligence
 */
export const CodeEditor: React.FC<CodeEditorProps> = ({
    value,
    onChange,
    language = 'plaintext',
    height = 200,
    placeholder,
    readOnly = false,
    theme = 'light',
    minimap = false
}) => {
    // Map our language types to Monaco language IDs
    const getMonacoLanguage = (lang: string): string => {
        if (lang === 'jinja2') {
            // Jinja2 can be treated as HTML with embedded templates
            return 'html';
        }
        return lang;
    };

    const handleChange = (newValue: string | undefined) => {
        onChange(newValue || '');
    };

    return (
        <div
            className="code-editor-wrapper"
            style={{
                border: '1px solid #e1e4e8',
                borderRadius: '8px',
                overflow: 'hidden',
                boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
                background: '#fafbfc',
                transition: 'all 0.2s ease'
            }}
        >
            <style>{`
                .code-editor-wrapper {
                    transition: border-color 0.2s ease, box-shadow 0.2s ease;
                }
                .code-editor-wrapper:hover {
                    border-color: #d1d5db !important;
                    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08) !important;
                }
                .code-editor-wrapper:focus-within {
                    border-color: #677eea !important;
                    box-shadow: 0 0 0 3px rgba(103, 126, 234, 0.1), 0 2px 8px rgba(0, 0, 0, 0.08) !important;
                }
                .code-editor-wrapper .margin-view-overlays {
                    width: 20px !important;
                }
                .code-editor-wrapper .monaco-editor .line-numbers {
                    width: 20px !important;
                    color: #9ca3af !important;
                    font-size: 11px !important;
                }
                .code-editor-wrapper .monaco-editor .line-numbers.active-line-number {
                    color: #677eea !important;
                }
                .code-editor-wrapper .monaco-editor {
                    background: #ffffff !important;
                }
                .code-editor-wrapper .monaco-editor .margin {
                    background: #fafbfc !important;
                }
                .code-editor-wrapper .monaco-editor .current-line {
                    border: none !important;
                    background: rgba(103, 126, 234, 0.03) !important;
                }
            `}</style>
            <MonacoEditor
                height={height}
                language={getMonacoLanguage(language)}
                theme={theme}
                value={value}
                onChange={handleChange}
                options={{
                    readOnly,
                    minimap: { enabled: minimap },
                    wordWrap: 'on',
                    lineNumbers: 'on',
                    lineNumbersMinChars: 1,
                    glyphMargin: false,
                    folding: true,
                    lineDecorationsWidth: 8,
                    renderLineHighlight: 'all',
                    renderLineHighlightOnlyWhenFocus: true,
                    matchBrackets: 'always',
                    autoIndent: 'full',
                    tabSize: 2,
                    insertSpaces: true,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    fontSize: 13,
                    fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', Monaco, Menlo, Consolas, monospace",
                    fontLigatures: true,
                    lineHeight: 22,
                    letterSpacing: 0.5,
                    padding: { top: 12, bottom: 12 },
                    smoothScrolling: true,
                    cursorBlinking: 'smooth',
                    cursorSmoothCaretAnimation: 'on',
                    roundedSelection: true,
                    suggest: {
                        showKeywords: true,
                        showSnippets: true,
                    },
                    quickSuggestions: {
                        other: true,
                        comments: false,
                        strings: true,
                    },
                }}
            />
        </div>
    );
};
