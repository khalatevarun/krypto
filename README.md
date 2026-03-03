# Krypto

**Krypto** is a terminal-based AI coding agent built in Python. It pairs an LLM with a rich set of tools to act as an intelligent pair-programming assistant right in your terminal — reading, writing, and editing files, running shell commands, searching the web, and managing multi-step tasks, all from a single CLI.

---

## Features

### Interaction Modes
- **Interactive REPL** — launch `python main.py` with no arguments to start a persistent chat session where context is preserved across turns.
- **Single-shot mode** — pass a prompt directly (`python main.py "explain this codebase"`) to get a one-off answer without entering the REPL.
- **Working directory scoping** — use `-c <path>` to run the agent in a specific directory.

### Agentic Loop
Krypto runs a fully autonomous agentic loop:
1. The user's message is sent to the LLM together with the current conversation history.
2. The LLM streams back a response that may include one or more tool calls.
3. Each tool is invoked, and the result is fed back into the conversation.
4. The loop continues until the LLM produces a final text response or the maximum turn limit is reached.
5. Built-in **loop detection** prevents the agent from getting stuck repeating identical tool calls.

### Built-in Tools

| Tool | Kind | Description |
|------|------|-------------|
| `shell` | Shell | Execute shell commands (bash/cmd). Dangerous commands are blocked by a safety list. Sensitive environment variables (keys, tokens, secrets) are stripped by default. |
| `read_file` | Read | Read a text file with line numbers. Supports `offset` and `limit` for paginating large files. Binary files are rejected. |
| `write_file` | Write | Create or fully overwrite a file. Parent directories are created automatically. |
| `edit` | Write | Surgically replace an exact string in a file. Unique-match enforcement prevents accidental multi-line clobbers; `replace_all` opt-in for bulk replacements. Shows a unified diff on success. |
| `list_dir` | Read | List directory contents, sorted with directories first. Hidden files excluded by default. |
| `grep` | Read | Regex search across files in a directory tree. Skips binary files and common noise directories (`node_modules`, `.git`, etc.). |
| `glob` | Read | Find files by glob pattern (supports `**` for recursive matching). |
| `web_search` | Network | Search the web using DuckDuckGo and return titles, URLs, and snippets. |
| `web_fetch` | Network | Fetch the raw text content of a URL. |
| `memory` | Memory | Persist key-value facts across sessions (`set`, `get`, `delete`, `list`, `clear`). Stored in the OS user-data directory. |
| `todo` | Memory | Session-scoped task list (`add`, `complete`, `list`, `clear`) for tracking multi-step work within a single conversation. |

### Sub-Agents
Krypto supports spawning focused sub-agents — isolated agent instances with a restricted tool set and a specific goal prompt. Sub-agents run their own agentic loop and return a structured result to the parent agent.

A **Code Reviewer** sub-agent is built in (`subagent_code_reviewer`). It can only read files and provides feedback on bugs, code smells, and security issues without modifying anything.

Custom sub-agents can be defined in `.krypto/config.toml`:

```toml
[subagents.my_agent]
description = "Does X"
goal_prompt  = "You are a specialist in X. Use only read_file and grep."
allowed_tools = ["read_file", "grep"]
```

### Configuration
Krypto merges configuration from two layers (project overrides system):

| Layer | Location |
|-------|----------|
| System | `~/.config/krypto/config.toml` |
| Project | `<project_root>/.krypto/config.toml` |

Key options:

```toml
[model]
name        = "openai/gpt-4o"   # any OpenAI-compatible model ID
temperature = 0

[shell_environment]
exclude_patterns        = ["*KEY*", "*TOKEN*", "*SECRET*"]  # env vars to strip
ignore_default_excludes = false
set_vars                = { MY_VAR = "value" }

max_turns     = 100
allowed_tools = ["shell", "read_file", "edit"]  # restrict available tools
```

### AGENT.MD Support
Place an `AGENT.MD` file at the root of a project to give the agent project-specific instructions (coding conventions, test commands, architectural notes). Krypto automatically loads this file into the system prompt when the agent starts.

### Persistent Memory
The `memory` tool writes to `~/.local/share/krypto/user_memory.json` (Linux/macOS). Stored entries are automatically injected into the system prompt at the start of each session so the agent remembers user preferences and recurring context.

### Security
- **Blocked commands**: `rm -rf /`, fork bombs, `shutdown`, `reboot`, disk formatters, and similar destructive commands are rejected outright.
- **Env-var scrubbing**: Variables matching `*KEY*`, `*TOKEN*`, `*SECRET*` are removed from the shell environment before any command runs.
- **Path validation**: File tools resolve paths relative to the configured working directory and reject operations that fall outside the workspace.
- **Prompt injection defense**: The system prompt instructs the agent to ignore instructions embedded in file contents or command output.

---

## Technologies

| Category | Library / Tool |
|----------|----------------|
| Language | Python 3.12 |
| LLM API | [OpenAI Python SDK](https://github.com/openai/openai-python) — any OpenAI-compatible endpoint (`BASE_URL` + `API_KEY`) |
| CLI framework | [Click](https://click.palletsprojects.com/) |
| Terminal UI | [Rich](https://github.com/Textualize/rich) |
| Data validation | [Pydantic v2](https://docs.pydantic.dev/) |
| Async HTTP | [httpx](https://www.python-httpx.org/) |
| Web search | [ddgs](https://github.com/deedy5/duckduckgo_search) (DuckDuckGo) |
| Env variables | [python-dotenv](https://github.com/theskumar/python-dotenv) |
| Config/data dirs | [platformdirs](https://github.com/platformdirs/platformdirs) |
| Linter/formatter | [Ruff](https://docs.astral.sh/ruff/) |
| Async runtime | Python `asyncio` (stdlib) |

---

## Architecture

```
krypto/
├── main.py              # CLI entry point (Click), interactive REPL loop
├── agent/
│   ├── agent.py         # Agentic loop, tool dispatch, loop detection
│   ├── session.py       # Session state: client, context manager, tool registry
│   └── events.py        # Typed event stream (text delta, tool call, error, …)
├── client/
│   ├── llm_client.py    # AsyncOpenAI wrapper, streaming, retry with backoff
│   └── response.py      # Stream event / tool-call data models
├── tools/
│   ├── base.py          # Tool base class, ToolResult, FileDiff, ToolKind enum
│   ├── registry.py      # ToolRegistry: register, validate, invoke
│   └── builtin/         # One file per built-in tool (shell, read_file, edit, …)
├── config/
│   ├── config.py        # Pydantic Config model (model, shell env, subagents, …)
│   └── loader.py        # TOML loader, system + project config merge
├── context/
│   └── manager.py       # Conversation history, system prompt injection
├── prompts/
│   └── system.py        # System prompt builder (identity, env, tools, memory, …)
├── ui/
│   └── tui.py           # Rich-based TUI: panels, syntax highlighting, diffs
└── utils/               # Path helpers, text utilities, error types
```

---

## Quick Start

```bash
# Set your API key and (optionally) a custom base URL for any OpenAI-compatible provider
export API_KEY="sk-..."
export BASE_URL="https://openrouter.ai/api/v1"   # optional

# Interactive mode
python main.py

# Single-shot mode
python main.py "Refactor the auth module to use async/await"

# Run in a specific directory
python main.py -c /path/to/project "Add unit tests for the utils module"
```

### Interactive Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/config` | Display current configuration |
| `/model` | Switch the active model |
| `/approval` | Toggle tool-call approval mode |
| `/exit` | Exit the agent |
