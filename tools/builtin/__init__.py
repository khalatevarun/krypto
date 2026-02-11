from tools.base import Tool
from tools.builtin.edit_file import EditFileTool
from tools.builtin.read_file import ReadFileTool
from tools.builtin.write_file import WriteFileTool
__all__=[
    'ReadFileTool',
    'WriteFileTool',
    'EditFileTool'
]

def get_all_builtin_tools() -> list[type[Tool]]:
    return [
        ReadFileTool, WriteFileTool, EditFileTool
    ]
