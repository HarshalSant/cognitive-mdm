"""
LangGraph-based autonomous MDM agent.
Implements a ReAct loop: Reason â†' Act â†' Observe â†' Repeat.
"""

from __future__ import annotations

import json
import os
from typing import Any, TypedDict

import anthropic
import structlog

logger = structlog.get_logger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

# Tool definitions for the agent
MDM_TOOLS = [
    {
        "name": "find_duplicates",
        "description": "Find duplicate entity candidates for a given entity ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "The entity ID to check"},
                "threshold": {"type": "number", "description": "Similarity threshold 0-1"},
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_entity",
        "description": "Retrieve full entity details by ID",
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "scan_governance",
        "description": "Run PII detection and policy evaluation on an entity",
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_low_trust_entities",
        "description": "Get entities with trust score below a threshold",
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "description": "Maximum trust score"},
                "entity_type": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Mark the current task as complete with a summary",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "findings": {"type": "array", "items": {"type": "object"}},
                "actions_taken": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary"],
        },
    },
]


class AgentState(TypedDict):
    task: str
    task_input: dict[str, Any]
    messages: list[dict]
    tool_calls: list[dict]
    result: dict[str, Any] | None
    complete: bool
    iterations: int


class MDMAgent:
    """
    Autonomous MDM agent using Claude with tool use.
    Implements a capped ReAct loop for safety.
    """

    MAX_ITERATIONS = 10

    def __init__(self, tool_executor=None):
        self._client: anthropic.AsyncAnthropic | None = None
        self._tool_executor = tool_executor
        if ANTHROPIC_API_KEY:
            self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    async def run(self, task: str, task_input: dict[str, Any]) -> dict[str, Any]:
        if not self._client:
            return {
                "complete": False,
                "error": "LLM not configured",
                "task": task,
            }

        state: AgentState = {
            "task": task,
            "task_input": task_input,
            "messages": [],
            "tool_calls": [],
            "result": None,
            "complete": False,
            "iterations": 0,
        }

        system = f"""You are an autonomous Master Data Management agent.
Your task: {task}
Task context: {json.dumps(task_input, default=str)}

Use the available tools to investigate and complete this task.
Be methodical: gather information before drawing conclusions.
Call complete_task when you have finished your work."""

        state["messages"].append({
            "role": "user",
            "content": f"Execute this MDM task: {task}\nContext: {json.dumps(task_input, default=str)}",
        })

        while not state["complete"] and state["iterations"] < self.MAX_ITERATIONS:
            state["iterations"] += 1

            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=4096,
                system=system,
                tools=MDM_TOOLS,
                messages=state["messages"],
            )

            # Collect assistant content
            assistant_content = []
            for block in response.content:
                if hasattr(block, "text"):
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            state["messages"].append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                state["complete"] = True
                break

            # Execute tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    state["tool_calls"].append({"tool": tool_name, "input": tool_input})

                    if tool_name == "complete_task":
                        state["complete"] = True
                        state["result"] = tool_input
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Task marked complete.",
                        })
                    elif self._tool_executor:
                        try:
                            result = await self._tool_executor(tool_name, tool_input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            })
                        except Exception as e:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"Error: {e}",
                                "is_error": True,
                            })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Tool execution not available",
                        })

            if tool_results:
                state["messages"].append({"role": "user", "content": tool_results})

            if state["complete"]:
                break

        return {
            "complete": state["complete"],
            "iterations": state["iterations"],
            "tool_calls": state["tool_calls"],
            "result": state["result"],
            "reasoning": [
                m["content"] for m in state["messages"]
                if m["role"] == "assistant"
            ][-1] if state["messages"] else None,
        }
