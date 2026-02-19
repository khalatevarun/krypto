from tools.base import Tool
from tools.builtin.edit_file import EditFileTool
from tools.builtin.glob import GlobTool
from tools.builtin.grep import GrepTool
from tools.builtin.list_dir import ListDirTool
from tools.builtin.read_file import ReadFileTool
from tools.builtin.shell import ShellTool
from tools.builtin.todo import TodosTool
from tools.builtin.webfetch import WebFetch
from tools.builtin.websearch import WebSearch
from tools.builtin.write_file import WriteFileTool

__all__ = [
    "EditFileTool",
    "GlobTool",
    "GrepTool",
    "ListDirTool",
    "ReadFileTool",
    "ShellTool",
    "TodosTool",
    "WebFetch",
    "WebSearch",
    "WriteFileTool",
]

# Map tool class names to classes for easy lookup by name
TOOL_CLASS_MAP: dict[str, type[Tool]] = {
    "TodosTool": TodosTool,
    "ListDirTool": ListDirTool,
    "ReadFileTool": ReadFileTool,
    "WriteFileTool": WriteFileTool,
    "EditFileTool": EditFileTool,
    "ShellTool": ShellTool,
    "GrepTool": GrepTool,
    "GlobTool": GlobTool,
    "WebSearch": WebSearch,
    "WebFetch": WebFetch,
}


def get_tool_class_by_name(name: str) -> type[Tool]:
    """Get a tool class by its class name string."""
    if name not in TOOL_CLASS_MAP:
        raise ValueError(f"Unknown tool class: {name}. Available: {list(TOOL_CLASS_MAP.keys())}")
    return TOOL_CLASS_MAP[name]


def get_all_builtin_tools() -> list[type[Tool]]:
    return [
        TodosTool,
        ListDirTool,
        ReadFileTool,
        WriteFileTool,
        EditFileTool,
        ShellTool,
        GrepTool,
        GlobTool,
        WebSearch,
        WebFetch,
    ]
