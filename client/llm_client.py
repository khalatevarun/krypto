import asyncio
import time
import logging
from typing import Any, AsyncGenerator
from openai import APIConnectionError, APIError, AsyncOpenAI, RateLimitError

from client.response import StreamEventType, StreamEvent, TextDelta, TokenUsage, ToolCall, ToolCallDelta, parse_tool_call_arguments

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._max_retries: int = 3
    
    def get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key='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',
                base_url='https://openrouter.ai/api/v1'
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    def _build_tools(self, tools: list[dict[str,Any]]):
        return [
          {
              'type':'function',
              'function':{
                  'name':tool['name'],
                  'description': tool.get('description',""),
                  'parameters': tool.get('parameters',{'type':'object','properties':{}}),
              }
          }  for tool in tools
        ]

    async def chat_completion(self, messages: list[dict[str, Any]],tools: list[dict[str, Any]] | None = None, stream: bool = True) -> AsyncGenerator[StreamEvent, None]:

        client = self.get_client()

        kwargs = {
            "model": "z-ai/glm-4.5-air:free",
            "messages": messages,
            "stream": stream
        }

        if tools:
            kwargs['tools'] = self._build_tools(tools)
            kwargs['tool_choice'] ="auto"
        
        for attempt in range(self._max_retries + 1):
            try:
                logger.debug(f"[LLM] attempt={attempt} stream={stream} tools={bool(tools)} time={time.time():.0f}")
                
                if stream:
                    async for event in self._stream_response(client, kwargs):
                        yield event

                else:
                    event = await self._non_stream_response(client, kwargs)
                    yield event
                return
            except RateLimitError as e:
                # Try to extract reset time from headers
                wait_time = 2 ** attempt  # default exponential backoff
                resp = getattr(e, 'response', None)
                if resp and hasattr(resp, 'headers'):
                    reset_header = resp.headers.get('X-RateLimit-Reset')
                    if reset_header:
                        try:
                            reset_epoch = int(reset_header) / 1000  # ms to seconds
                            wait_time = max(1, reset_epoch - time.time())
                        except (ValueError, TypeError):
                            pass
                
                logger.warning(f"[LLM] Rate limit hit, attempt {attempt}, waiting {wait_time:.1f}s")
                if attempt < self._max_retries:
                    await asyncio.sleep(wait_time)
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f'Rate limit exceeded: {e}'
                    )
                    return
            except APIConnectionError as e:
                if attempt < self._max_retries:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                else:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f'Connection error: {e}'
                    )
                    return
            except APIError as e:
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=f'API error: {e}'
                )
                return


    async def _stream_response(self, client: AsyncOpenAI, kwargs: dict[str, Any]) -> AsyncGenerator[StreamEvent,None]:
        response = await client.chat.completions.create(**kwargs)
        usage: TokenUsage | None = None
        finish_reason: str | None = None
        tool_calls: dict[int, dict[str,Any]] = {}
        async for chunk in response:

            if hasattr(chunk,"usage") and chunk.usage:
                usage = TokenUsage(
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                    cached_tokens=chunk.usage.prompt_tokens_details.cached_tokens
                    )
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            if choice.finish_reason:
                finish_reason = choice.finish_reason
            
            if delta.content:
                yield StreamEvent(
                    type = StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta(delta.content),
                )

            if delta.tool_calls:
                for tool_call_delta in delta.tool_calls:
                    idx = tool_call_delta.index
                    if idx not in tool_calls:
                        tool_calls[idx]={
                            'id':tool_call_delta.id or "",
                            'name': '',
                            'arguments':''
                        }

                        if tool_call_delta.function:
                            if tool_call_delta.function.name:
                                tool_calls[idx]['name']= tool_call_delta.function.name
                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL_DETAILS_START,
                                    tool_call_delta=ToolCallDelta(
                                        call_id=tool_calls[idx]['id'],
                                        name=tool_calls[idx]['name'],
                                    )
                                )
                            if tool_call_delta.function.arguments:
                                tool_calls[idx]['arguments'] += tool_call_delta.function.arguments
                                yield StreamEvent(
                                    type=StreamEventType.TOOL_CALL__DETAILS_DELTA,
                                    tool_call_delta=ToolCallDelta(
                                        call_id=tool_calls[idx]['id'],
                                        name=tool_calls[idx]['name'],
                                        arguments_delta=tool_call_delta.function.arguments
                                    )
                                )

        for idx, tc in tool_calls.items():
            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_DETAILS_COMPLETE,
                                tool_call=ToolCall(
                                    call_id=tc['id'],
                                    name=tc['name'],
                                    arguments=parse_tool_call_arguments(tc['arguments'])
                                )
                            ) 
    
        yield StreamEvent(
            type = StreamEventType.MESSAGE_COMPLETE,
            finish_reason=finish_reason,
            usage = usage
        )
    
    async def _non_stream_response(self, client: AsyncOpenAI, kwargs: dict[str, Any])  -> StreamEvent:
        response = await client.chat.completions.create(**kwargs) 
        ## ** mean deconstructing the args 
        choice = response.choices[0]
        message = choice.message
        text_delta = None
        if message.content:
            text_delta = TextDelta(content=message.content)

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    call_id=tc.id,
                    name=tc.function.name,
                    arguments=parse_tool_call_arguments(tc.function.arguments)
                ))

        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                cached_tokens=response.usage.prompt_tokens_details.cached_tokens
            )

        return StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            text_delta=text_delta,
            finish_reason=choice.finish_reason,
            usage=usage,
        )