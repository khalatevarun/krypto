import json

from pydantic import BaseModel, Field

from config.loader import get_data_dir
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class MemoryParams(BaseModel):
    action: str = Field(..., description="Action: 'set', 'get', 'delete', 'list', 'clear'")
    key: str | None = Field(..., description="Memory key (required for `set`, `get`, and `delete`)")
    value: str | None = Field(None, description="Value to store (required for `set`)")


class MemoryTool(Tool):
    name = "memory"
    description = "Store and retrieve persistent memory. Use this to remember user preferences, important context"
    kind = ToolKind.MEMORY

    def _load_memory(self) -> dict:
        data_dir = get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "user_memory.json"

        if not path.exists():
            return {"entries": {}}

        try:
            content = path.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception:
            return {"entries": {}}

    def _save_memory(self, memory: dict) -> None:
        data_dir = get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / "user_memory.json"

        path.write_text(json.dumps(memory, indent=2, ensure_ascii=False))

    @property
    def schema(self) -> type[MemoryParams]:
        return MemoryParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = MemoryParams(**invocation.params)

        if params.action.lower() == "set":
            if not params.key or not params.value:
                return ToolResult.error_result("`key` and `value` are required for `set` action")
            memory = self._load_memory()
            memory["entries"][params.key] = params.value
            self._save_memory(memory)

            return ToolResult.success_result(f"Set memory: {params.key}")
        elif params.action.lower() == "get":
            if not params.key:
                return ToolResult.error_result("`key` is required for `get` action")

            memory = self._load_memory()

            if params.key not in memory.get("entries", {}):
                return ToolResult.success_result(f"Memory not found: {params.key}")

            return ToolResult.success_result(
                f"Memory found: {params.key}: {memory['entries'][params.key]}"
            )

        elif params.action.lower() == "delete":
            if not params.key:
                return ToolResult.error_result("`key` is required for `delete` action")

            memory = self._load_memory()

            if params.key not in memory.get("entries", {}):
                return ToolResult.success_result(f"Memory not found: {params.key}")

            del memory["entries"][params.key]
            self._save_memory(memory)

            return ToolResult.success_result(f"Deleted memory : {params.key}")

        elif params.action.lower() == "list":
            memory = self._load_memory()
            entries = memory.get("entries", {})
            if not entries:
                return ToolResult.success_result("No memories stored")
            lines = ["Stored memories: "]
            for key, value in sorted(entries.items()):
                lines.append(f" {key}: {value}")

            return ToolResult.success_result("\n".join(lines))

        elif params.action.lower() == "clear":
            memory = self._load_memory()
            entries = memory.get("entries", {})
            count = len(entries)
            memory["entries"] = {}
            self._save_memory(memory)

            return ToolResult.success_result(f"Cleared {count} memory entries")

        else:
            return ToolResult.error_result(f"Uknown action: {params.action}")
