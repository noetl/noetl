# AI Coding Agent Setup

This project includes AI agent instructions in `.github/ai-instructions.md` to help coding assistants understand the NoETL architecture and development patterns.

## Setup Instructions by AI Agent

### GitHub Copilot (VS Code)
- **Automatic**: Instructions are automatically loaded from `.github/copilot-instructions.md` (symlinked to `ai-instructions.md`)
- **Manual**: Explicitly configured in `.vscode/settings.json` via `github.copilot.chat.instructionFiles`
- **Usage**: Simply use Copilot chat or inline suggestions - instructions are automatically applied

### Cursor
- **Method 1**: Place instructions in `.cursorrules` file (root of project)
- **Method 2**: Reference in Cursor settings under "Rules for AI"
- **Usage**: Instructions automatically apply to all AI interactions

### Claude (via Codebase Context)
- **Method**: Include `.github/ai-instructions.md` in your conversation context
- **Usage**: Reference the file when starting a conversation: "Use the instructions in `.github/ai-instructions.md`"

### Codeium
- **Method**: Configure in Codeium extension settings under "Custom Instructions"
- **Usage**: Instructions apply automatically to completions and chat

### Continue (VS Code Extension)
- **Method**: Add to `continue/config.json` under `systemMessage`
- **Usage**: Instructions apply to all Continue interactions

## Universal Approach

For any AI coding agent:
1. **Reference the file**: Start conversations with "Follow the guidelines in `.github/ai-instructions.md`"
2. **Copy content**: Paste relevant sections into your AI chat interface
3. **Context inclusion**: Always include the file in your codebase context when asking for help

## Key Instruction Highlights

The AI instructions cover:
- NoETL's event-driven architecture with server-worker coordination
- Playbook-based development workflows using the `noetl` CLI
- Playbook YAML structure and patterns
- Plugin development guidelines
- Testing patterns and credential management

## For New Team Members

When onboarding with any AI coding assistant:
1. Point your AI agent to `.github/ai-instructions.md`
2. Reference the file when asking architecture questions
3. Use the documented `noetl` CLI commands for development workflows