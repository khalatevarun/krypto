"""
Braintrust eval: measure how tool ordering affects agent behavior.

Systematically moves TodosTool across positions in the tools list
and evaluates the same prompt ("build a whatsapp clone") to see how
tool order influences the LLM's execution strategy.

Run:
    braintrust eval --no-send-logs evals/tool_order_eval.py   # local only (no API key needed)
    braintrust eval evals/tool_order_eval.py                  # send to Braintrust (needs BRAINTRUST_API_KEY)

API budget (default settings):
    3 orderings × 1 trial × up to 3 turns = ~9 LLM calls
"""

from __future__ import annotations

import json
import sys
import os

# Ensure project root is on sys.path so imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import braintrust
from openai import AsyncOpenAI

from config.config import Config
from client.response import (
    ToolCall,
    parse_tool_call_arguments,
)
from context.manager import ContextManager
from tools.builtin import get_tool_class_by_name, TOOL_CLASS_MAP
from tools.registry import create_registry_with_order

# ---------------------------------------------------------------------------
# Constants — tune these to control API call budget
# ---------------------------------------------------------------------------

PROMPT = "build a whatsapp clone"

# Maximum agentic turns per eval run. Each turn = 1 LLM call.
# With 3 orderings × 1 trial × 3 turns = ~9 API calls total.
MAX_EVAL_TURNS = int(os.environ.get("EVAL_MAX_TURNS", "3"))

# Default tool order (mirrors get_all_builtin_tools)
DEFAULT_ORDER = [
    "TodosTool",
    "ListDirTool",
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "ShellTool",
    "GrepTool",
    "GlobTool",
    "WebSearch",
    "WebFetch",
]

# We keep the other 9 tools in their relative order and insert TodosTool
# at different positions.
OTHER_TOOLS = [t for t in DEFAULT_ORDER if t != "TodosTool"]


def _make_order(todo_position: int) -> list[str]:
    """Insert TodosTool at `todo_position` among the other 9 tools."""
    order = list(OTHER_TOOLS)
    order.insert(todo_position, "TodosTool")
    return order


# 3 targeted positions: first, middle, last — the key comparison
TOOL_ORDERINGS: list[dict] = [
    {
        "label": "todos_first",
        "description": "TodosTool first (default)",
        "order": _make_order(0),
    },
    {
        "label": "todos_middle",
        "description": "TodosTool at position 5 (middle)",
        "order": _make_order(5),
    },
    {
        "label": "todos_last",
        "description": "TodosTool last (after WebSearch, WebFetch)",
        "order": _make_order(9),
    },
]

# ---------------------------------------------------------------------------
# Lightweight agentic loop for eval (mirrors agent/agent.py logic)
# ---------------------------------------------------------------------------


async def run_agent_for_eval(
    prompt: str,
    config: Config,
    tool_order: list[str],
    max_turns: int = MAX_EVAL_TURNS,
) -> dict:
    """
    Run a stripped-down agentic loop with a specific tool ordering.

    Returns a dict with:
      - tool_calls: list of {name, arguments} in execution order
      - final_output: concatenated text the agent produced
      - turns: number of LLM turns taken
    """
    # Build registry in the requested order
    tool_classes = [get_tool_class_by_name(name) for name in tool_order]
    registry = create_registry_with_order(config, tool_classes)

    # Wrap the AsyncOpenAI client for Braintrust tracing
    raw_client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
    )
    traced_client = braintrust.wrap_openai(raw_client)

    # Context with system prompt
    ctx = ContextManager(config)
    ctx.add_user_message(prompt)

    all_tool_calls: list[dict] = []
    all_text = ""
    turns_taken = 0

    for turn in range(max_turns):
        turns_taken = turn + 1
        tool_schemas = registry.get_schemas()
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tool_schemas
        ]

        response = await traced_client.chat.completions.create(
            model=config.model_name,
            messages=ctx.get_messages(),
            tools=openai_tools,
            tool_choice="auto",
            stream=False,
        )

        choice = response.choices[0]
        message = choice.message
        response_text = message.content or ""
        all_text += response_text

        # Parse tool calls from the response
        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        call_id=tc.id,
                        name=tc.function.name,
                        arguments=parse_tool_call_arguments(tc.function.arguments),
                    )
                )

        # Add assistant message to context
        ctx.add_assistant_message(
            response_text,
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

        if not tool_calls:
            break

        # Execute each tool call
        for tc in tool_calls:
            all_tool_calls.append({"name": tc.name, "arguments": tc.arguments})

            result = await registry.invoke(tc.name or "", tc.arguments, config.cwd)

            ctx.add_tool_result(tc.call_id, result.to_model_output())

    await raw_client.close()

    return {
        "tool_calls": all_tool_calls,
        "final_output": all_text,
        "turns": turns_taken,
        "first_tool": all_tool_calls[0]["name"] if all_tool_calls else None,
        "tool_call_names": [tc["name"] for tc in all_tool_calls],
    }


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------


def todo_first_scorer(*, output, **kwargs) -> dict:
    """Score 1.0 if the very first tool call is the todos/planning tool."""
    tool_calls = output.get("tool_calls", [])
    if not tool_calls:
        return {"name": "todo_first", "score": 0.0, "metadata": {"reason": "no tool calls"}}

    first = tool_calls[0]["name"]
    is_todo = first in ("todos", "todo", "TodosTool")
    return {
        "name": "todo_first",
        "score": 1.0 if is_todo else 0.0,
        "metadata": {"first_tool": first},
    }


def planning_before_action_scorer(*, output, **kwargs) -> dict:
    """
    Score = fraction of tools before the first 'action' tool that are
    'planning/research' tools.

    Planning tools: todos, list_dir, read_file, grep, glob
    Action tools:   write_file, edit_file, shell
    Network tools:  web_search, web_fetch (treated as research)
    """
    planning = {"todos", "list_dir", "read_file", "grep", "glob", "web_search", "web_fetch"}
    action = {"write_file", "edit_file", "shell"}

    tool_names = output.get("tool_call_names", [])
    if not tool_names:
        return {"name": "planning_before_action", "score": 0.0, "metadata": {"reason": "no tools"}}

    # Find index of first action tool
    first_action_idx = None
    for i, name in enumerate(tool_names):
        if name in action:
            first_action_idx = i
            break

    if first_action_idx is None:
        # No action tools used at all → all planning/research
        return {
            "name": "planning_before_action",
            "score": 1.0,
            "metadata": {"tools_before_action": tool_names, "first_action_idx": None},
        }

    if first_action_idx == 0:
        return {
            "name": "planning_before_action",
            "score": 0.0,
            "metadata": {"tools_before_action": [], "first_action_idx": 0},
        }

    before_action = tool_names[:first_action_idx]
    planning_count = sum(1 for t in before_action if t in planning)
    score = planning_count / len(before_action) if before_action else 0.0

    return {
        "name": "planning_before_action",
        "score": score,
        "metadata": {
            "tools_before_action": before_action,
            "first_action_idx": first_action_idx,
            "planning_count": planning_count,
        },
    }


def tool_call_diversity_scorer(*, output, **kwargs) -> dict:
    """Score based on the number of unique tools used (normalized to 0-1)."""
    tool_names = output.get("tool_call_names", [])
    unique = set(tool_names)
    total_tools = len(TOOL_CLASS_MAP)
    score = len(unique) / total_tools if total_tools else 0.0

    return {
        "name": "tool_diversity",
        "score": min(score, 1.0),
        "metadata": {"unique_tools": list(unique), "count": len(unique)},
    }


# ---------------------------------------------------------------------------
# Data: one eval case per tool ordering
# ---------------------------------------------------------------------------


def eval_data():
    """Generate one EvalCase per tool ordering permutation."""
    cases = []
    for ordering in TOOL_ORDERINGS:
        cases.append(
            {
                "input": {
                    "prompt": PROMPT,
                    "tool_order": ordering["order"],
                    "order_label": ordering["label"],
                    "order_description": ordering["description"],
                },
                "metadata": {
                    "tool_order_label": ordering["label"],
                    "tool_order": ordering["order"],
                },
            }
        )
    return cases


# ---------------------------------------------------------------------------
# Task: run the agent with the specified tool ordering
# ---------------------------------------------------------------------------


async def eval_task(input, hooks=None):
    """Run the agentic loop with the specified tool ordering and return results."""
    config = Config()

    # Log the tool order as metadata on the span
    if hooks and hasattr(hooks, "metadata"):
        hooks.metadata["tool_order_label"] = input["order_label"]
        hooks.metadata["tool_order"] = input["tool_order"]

    result = await run_agent_for_eval(
        prompt=input["prompt"],
        config=config,
        tool_order=input["tool_order"],
        max_turns=MAX_EVAL_TURNS,
    )

    return result


# ---------------------------------------------------------------------------
# Braintrust Eval registration
# ---------------------------------------------------------------------------

braintrust.Eval(
    "Krypto Tool Order Eval",
    data=eval_data,
    task=eval_task,
    scores=[
        todo_first_scorer,
        planning_before_action_scorer,
        tool_call_diversity_scorer,
    ],
    experiment_name="tool-order-todos-sweep",
    trial_count=1,
    max_concurrency=1,
    metadata={
        "model": "z-ai/glm-4.5-air:free",
        "prompt": PROMPT,
        "max_eval_turns": MAX_EVAL_TURNS,
        "description": "Evaluating how TodosTool position in the tools list affects agent behavior",
    },
)
