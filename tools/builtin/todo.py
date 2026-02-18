import uuid
from typing import Literal

from pydantic import BaseModel, Field

from config.config import Config
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class TodosParams(BaseModel):
    action: Literal["add", "complete", "list", "clear"] = Field(
        ...,
        description="Action to perform on the todo list",
    )
    id: str | None = Field(
        None,
        description="Todo ID (for complete)",
    )
    content: str | None = Field(None, description="Todo content (for add)")


class TodosTool(Tool):
    name = "todo"
    description = (
        "Manage task list for the current session. Use this to track progress on multi-step tasks."
    )
    kind = ToolKind.MEMORY

    @property
    def schema(self) -> type[TodosParams]:
        return TodosParams

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._todos: dict[str, str] = {}

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = TodosParams(**invocation.params)

        if params.action == "add":
            if not params.content:
                return ToolResult.error_result("`content` is required for `add` action")
            todo_id = str(uuid.uuid4())[:8]
            self._todos[todo_id] = params.content
            return ToolResult.success_result(f"Added todo [{todo_id}] : {params.content}")
        elif params.action == "complete":
            if not params.id:
                return ToolResult.error_result("`ID` required for `complete` action")
            if params.id not in self._todos:
                return ToolResult.error_result(f"Todo not found: {params.id}")

            content = self._todos.pop(params.id)
            return ToolResult.success_result(f"Completed todo [{params.id}]: {content}")
        elif params.action == "list":
            if not self._todos:
                return ToolResult.success_result("No todos left")
            lines = ["Todos:"]

            for todo_id, content in self._todos.items():
                lines.append(f"    [{todo_id}] {content}")
            return ToolResult.success_result("\n".join(lines))
        else:  # clear
            count = len(self._todos)
            self._todos.clear()
            return ToolResult.success_result(f"Cleared {count} todos")
