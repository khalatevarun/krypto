from typing import Any, AsyncGenerator
from openai import AsyncOpenAI

from client.response import EventType, StreamEvent, TextDelta, TokenUsage

class LLMClient:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
    
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

    async def chat_completion(self, messages: list[dict[str, Any]], stream: bool = True) -> AsyncGenerator[StreamEvent, None]:
        client = self.get_client()

        kwargs = {
            "model": "mistralai/devstral-2512:free",
            "messages": messages,
            "stream": stream
        }


        if stream:
            await self._stream_response()
        else:
           event = await self._non_stream_response(client, kwargs)
           yield event
        return

    async def _stream_response(self):
        pass

    async def _non_stream_response(self, client: AsyncOpenAI, kwargs: dict[str, Any])  -> StreamEvent:
        response = await client.chat.completions.create(**kwargs) 
        ## ** mean deconstructing the args 
        choice = response.choices[0]
        message = choice.message
        text_delta = None
        if message.content:
            text_delta = TextDelta(content=message.content)

        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                cached_tokens=response.usage.prompt_tokens_details.cached_tokens
            )

        return StreamEvent(
            type=EventType.MESSAGE_COMPLETE,
            text_delta=text_delta,
            finish_reason=choice.finish_reason,
            usage=usage,
        )