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
        <div style={{
            border: '1px solid #d9d9d9',
            borderRadius: '4px',
            overflow: 'hidden'
        }}>
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
                    folding: true,
                    matchBrackets: 'always',
                    autoIndent: 'full',
                    tabSize: 2,
                    insertSpaces: true,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    fontSize: 13,
                    lineHeight: 20,
                    padding: { top: 8, bottom: 8 },
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
