from __future__ import annotations
import json
from typing import AsyncGenerator

from agent.events import AgentEvent, AgentEventType
from agent.session import Session
from client.response import StreamEventType, ToolCall, ToolResultMessage
from config.config import Config

class Agent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session: Session | None = Session(config)

    async def run(self, message:str):
        if self.session is None:
            raise RuntimeError("Session is not initialized")

        yield AgentEvent.agent_start(message)
        # add user message to context
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

        max_turns = self.session.config.max_turns
        recent_tool_calls: list[tuple[str, str]] = []  # (name, args_json) for loop detection

        for turn in range(max_turns):
            self.session.increment_turn()
            response_text = ""
            tools_schemas = self.session.tool_registry.get_schemas()
            tool_calls: list[ToolCall] = []
            

            async for event in self.session.client.chat_completion(self.session.context_manager.get_messages(),tools=tools_schemas if tools_schemas else None , stream=True): # type: ignore
                
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

            self.session.context_manager.add_assistant_message(
                response_text or '', 
                [
                    {
                        'id':tc.call_id,
                        'type': 'function',
                        'function': {'name': tc.name, 'arguments': json.dumps(tc.arguments)}
                    }
                    for tc in tool_calls
                ] if tool_calls else []
            )
            if response_text:
                yield AgentEvent.text_complete(response_text)
            
            if not tool_calls:
                return

            # --- loop detection ---
            current_signatures = [
                (tc.name or "", json.dumps(tc.arguments, sort_keys=True))
                for tc in tool_calls
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
                    arguments=tool_call.arguments
                )

                result = await self.session.tool_registry.invoke(
                    tool_call.name or "",
                    tool_call.arguments,
                    self.config.cwd
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
                self.session.context_manager.add_tool_result(
                    tool_result.tool_call_id,
                    tool_result.content
                )

    async def __aenter__(self) -> Agent:
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.session and self.session.client:
            await self.session.client.close()
            self.session = None
