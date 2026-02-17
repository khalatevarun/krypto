import httpx
from pydantic import BaseModel, Field, HttpUrl
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult

class WebFetchParams(BaseModel):
    url: HttpUrl = Field(...,description="URL to fetch (must be http:// or https://)")
    timeout: int = Field(30,ge=5,le=120,description="Request timeout in seconds(default: 30)")


class WebFetch(Tool):
    name = 'web_fetch'
    description = 'Fetch content from a url. Returns the response body as text'
    tool_kind = ToolKind.NETWORK

    @property
    def schema(self) -> type[WebFetchParams]:
        return WebFetchParams
    
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebFetchParams(**invocation.params)

        try:
           async with httpx.AsyncClient(
               timeout=httpx.Timeout(params.timeout),
               follow_redirects=True
           ) as client:
               response = await client.get(str(params.url))
               response.raise_for_status()
               text = response.text
        except httpx.HTTPStatusError as e:
            return ToolResult.error_result(f"HTTP: {e.response.status_code}: {e.response.reason_phrase}")
        except Exception as e:
            return ToolResult.error_result(f"Request failed: {e}")
        
        if len(text) > 100 * 1024:
            text = text[: 100 * 1024] + "\n... [content truncated]"
        
        return ToolResult.success_result(
            text,
            metadata={
                "status_code": response.status_code,
                "content_length": len(response.content)
            }
        )

    
