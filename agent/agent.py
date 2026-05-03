from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from agent.events import AgentEvent, AgentEventType
from agent.session import Session
from client.response import StreamEventType, TokenUsage, ToolCall, ToolResultMessage
from config.config import Config


class Agent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session: Session | None = Session(config)
        # Ensure context_manager is initialized
        if self.session and not hasattr(self.session, "context_manager"):
            raise AttributeError("Session missing context_manager attribute")

    async def run(self, message: str):
        if self.session is None:
            raise RuntimeError("Session is not initialized")

        yield AgentEvent.agent_start(message)
        # add user message to context
        if not self.session.context_manager:
            raise AttributeError("Session context_manager is None")
        self.session.context_manager.add_user_message(message)

        final_response: str | None = None

        async for event in self._agentic_loop():
            yield event

            if event.type == AgentEventType.TEXT_COMPLETE:
                final_response = event.data.get("content")

        yield AgentEvent.agent_end(final_response)

    async def _agentic_loop(self) -> AsyncGenerator[AgentEvent, None]:
        if self.session is None:
            raise RuntimeError("Session is not initialized")

        if (
            self.session.context_manager is not None
            and self.session.context_manager.needs_compression()
        ):
            summary, usage = await self.session.chatcompactor.compress(self.session.context_manager)

            if summary and usage:
                self.session.context_manager.replace_with_summary(summary)
                self.session.context_manager.set_latest_usage(usage)
                self.session.context_manager.add_usage(usage)

        max_turns = self.session.config.max_turns
        recent_tool_calls: list[tuple[str, str]] = []  # (name, args_json) for loop detection

        for _ in range(max_turns):
            self.session.increment_turn()
            response_text = ""

            tools_schemas = self.session.tool_registry.get_schemas()
            tool_calls: list[ToolCall] = []
            usage: TokenUsage | None = None

            if not self.session.context_manager:
                raise AttributeError("Session context_manager is None")
            async for event in self.session.client.chat_completion(
                self.session.context_manager.get_messages(),
                tools=tools_schemas if tools_schemas else None,
                stream=True,
            ):  # type: ignore
                if event.type == StreamEventType.TEXT_DELTA:
                    if event.text_delta:
                        content = event.text_delta.content
                        response_text += content
                        yield AgentEvent.text_delta(content)
                elif event.type == StreamEventType.TOOL_CALL_DETAILS_COMPLETE:
                    if event.tool_call:
                        tool_calls.append(event.tool_call)

                elif event.type == StreamEventType.ERROR:
                    yield AgentEvent.agent_error(event.error or "Uknown error occured.")
                elif event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage

            if not self.session.context_manager:
                raise AttributeError("Session context_manager is None")
            self.session.context_manager.add_assistant_message(
                response_text or "",
                [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in tool_calls
                ]
                if tool_calls
                else [],
            )
            if response_text:
                yield AgentEvent.text_complete(response_text)

            if not tool_calls:
                if usage:
                    self.session.context_manager.set_latest_usage(usage)
                    self.session.context_manager.add_usage(usage)
                return

            # --- loop detection ---
            current_signatures = [
                (tc.name or "", json.dumps(tc.arguments, sort_keys=True)) for tc in tool_calls
            ]
            if current_signatures == recent_tool_calls:
                yield AgentEvent.text_delta(
                    "\n[Loop detected — the same tool calls were repeated. Stopping.]\n"
                )
                return
            recent_tool_calls = current_signatures

            tool_call_results: list[ToolResultMessage] = []

            for tool_call in tool_calls:
                yield AgentEvent.tool_call_start(
                    call_id=tool_call.call_id,
                    name=tool_call.name or "",
                    arguments=tool_call.arguments,
                )

                result = await self.session.tool_registry.invoke(
                    tool_call.name or "", tool_call.arguments, self.config.cwd
                )

                yield AgentEvent.tool_call_complete(
                    tool_call.call_id,
                    tool_call.name or "",
                    result,
                )

                tool_call_results.append(
                    ToolResultMessage(
                        tool_call_id=tool_call.call_id,
                        content=result.to_model_output(),
                        is_error=not result.success,
                    )
                )

            for tool_result in tool_call_results:
                if not self.session.context_manager:
                    raise AttributeError("Session context_manager is None")
                self.session.context_manager.add_tool_result(
                    tool_result.tool_call_id, tool_result.content
                )

            if usage:
                self.session.context_manager.set_latest_usage(usage)
                self.session.context_manager.add_usage(usage)

        # TODO: notify the user using AgentEvent that the compaction took place - a good user experience

        yield AgentEvent.agent_error(f"Maximum turns ({max_turns}) reached")

    async def __aenter__(self) -> Agent:
        if not self.session:
            raise RuntimeError("Session is not initialized")
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.session and self.session.client:
            await self.session.client.close()
            await self.session.mcp_manager.shutdown()
            self.session = None
