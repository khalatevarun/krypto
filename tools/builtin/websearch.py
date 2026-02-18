from ddgs import DDGS
from pydantic import BaseModel, Field
from tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class WebSearchParams(BaseModel):
    query: str = Field(..., description="Search query")
    max_results: int = Field(10, ge=0, le=20, description="Maximum result to return (default: 10)")


class WebSearch(Tool):
    name = "web_search"
    description = (
        "Search the web for information. Returns search results with titles, URLS and snippets"
    )
    tool_kind = ToolKind.NETWORK

    @property
    def schema(self) -> type[WebSearchParams]:
        return WebSearchParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebSearchParams(**invocation.params)

        try:
            results = DDGS().text(
                params.query,
                region="us-en",
                safesearch="off",
                timelimit="y",
                page=1,
                backend="auto",
                max=params.max_results,
            )

        except Exception as e:
            return ToolResult.error_result(f"Search failed: {e}")

        if not results:
            return ToolResult.success_result(
                f"No results found for: {params.query}", metadata={"results": 0}
            )

        output_lines = [f"Search results for: {params.query}"]

        for i, result in enumerate(results, 1):
            output_lines.append(f"{i}. Title: {result['title']}")
            output_lines.append(f"  URL: {result['href']}")
            if result.get("body"):
                output_lines.append(f" Snippet: {result['body']}")

            output_lines.append("")

        return ToolResult.success_result(
            "\n".join(output_lines), metadata={"results": len(results)}
        )
