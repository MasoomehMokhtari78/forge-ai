"""
Provider-independent Agent LLM interfaces, MockAgentLLMService, and provider factory.
"""

from abc import ABC, abstractmethod
import json
import logging
import re
from typing import Any

from app.core.config import settings
from app.schemas.agent import (
    AgentLLMResponse,
    AgentMessage,
    AgentMessageRole,
    AgentToolDefinition,
    ToolCall,
    ToolName,
)

logger = logging.getLogger(__name__)


class AgentLLMService(ABC):
    """Provider-independent interface for Agent LLMs supporting tool calling."""

    @abstractmethod
    async def generate(
        self,
        messages: list[AgentMessage],
        tools: list[AgentToolDefinition] | None = None,
    ) -> AgentLLMResponse:
        """Generate either structured tool calls or a final text response."""
        ...


class MockAgentLLMService(AgentLLMService):
    """Deterministic mock LLM provider generating structured decisions for the agent loop.

    Features:
      1. Implements provider-independent AgentLLMService.
      2. Scriptable mode: can receive a sequence of canned actions/answers for deterministic unit tests.
      3. Autonomous heuristic mode: generates realistic multi-step decisions
         (search -> read -> final) based on the investigation history in the messages.
      4. Backward compatibility: also supports generate(prompt: str) -> str.
    """

    def __init__(
        self,
        scripted_responses: list[AgentLLMResponse | dict[str, Any] | str] | None = None,
    ) -> None:
        self._scripted: list[AgentLLMResponse] = []
        if scripted_responses:
            for item in scripted_responses:
                self._scripted.append(self._normalize_response(item))
        self._call_count: int = 0

    @staticmethod
    def _normalize_response(item: AgentLLMResponse | dict[str, Any] | str) -> AgentLLMResponse:
        """Convert a raw string, dict, or AgentLLMResponse into a normalized AgentLLMResponse."""
        if isinstance(item, AgentLLMResponse):
            return item

        if isinstance(item, str):
            try:
                data = json.loads(item.strip())
            except Exception:
                return AgentLLMResponse(final_text=item)
        else:
            data = item

        # Check for tool call
        if data.get("type") == "tool" or "tool" in data or "name" in data:
            tool_name = data.get("tool") or data.get("name")
            args = data.get("arguments", {})
            return AgentLLMResponse(
                tool_calls=[ToolCall(tool=ToolName(tool_name), arguments=args)]
            )

        # Check for final answer
        if data.get("type") == "final" or "answer" in data or "final_text" in data:
            answer = data.get("answer") or data.get("final_text", "")
            return AgentLLMResponse(final_text=answer)

        # Direct tool_calls list in dict
        if "tool_calls" in data:
            tcs = [
                ToolCall(tool=ToolName(tc.get("tool") or tc.get("name")), arguments=tc.get("arguments", {}))
                for tc in data["tool_calls"]
            ]
            return AgentLLMResponse(final_text=data.get("final_text"), tool_calls=tcs)

        return AgentLLMResponse(final_text=str(data))

    async def generate(
        self,
        messages: list[AgentMessage] | str,
        tools: list[AgentToolDefinition] | None = None,
    ) -> AgentLLMResponse:
        """Produce an AgentLLMResponse given agent messages or a string prompt."""
        # 1. Scripted mode (for unit testing specific loop sequences)
        if self._scripted:
            if self._call_count < len(self._scripted):
                response = self._scripted[self._call_count]
                self._call_count += 1
                return response
            # Fallback if script runs out: complete with final answer
            return AgentLLMResponse(final_text="[MOCK AGENT] Scripted sequence completed.")

        # Handle backward-compatibility where a raw string prompt is passed
        if isinstance(messages, str):
            return self._generate_from_prompt_string(messages)

        # 2. Autonomous heuristic mode for list[AgentMessage]
        question = "repository code"
        for msg in messages:
            if msg.role == AgentMessageRole.USER and msg.content:
                question = msg.content
                break

        # Check which tools have been called or returned observations
        executed_tools: list[str] = []
        last_search_observation: str | None = None
        for msg in messages:
            if msg.role == AgentMessageRole.ASSISTANT:
                for tc in msg.tool_calls:
                    executed_tools.append(tc.tool.value)
            elif msg.role == AgentMessageRole.TOOL:
                if msg.tool_name:
                    executed_tools.append(msg.tool_name)
                    if msg.tool_name == ToolName.SEARCH_CODE.value:
                        last_search_observation = msg.content

        # Step A: If search_code has not executed yet, search first
        if ToolName.SEARCH_CODE.value not in executed_tools:
            return AgentLLMResponse(
                tool_calls=[
                    ToolCall(
                        tool=ToolName.SEARCH_CODE,
                        arguments={"query": question, "top_k": 5},
                    )
                ]
            )

        # Step B: If search succeeded and read_file has not run yet, read top match
        if ToolName.READ_FILE.value not in executed_tools and last_search_observation:
            path_match = re.search(r'"path":\s*"([^"]+)"', last_search_observation)
            if path_match:
                top_path = path_match.group(1)
                start_match = re.search(r'"start_line":\s*(\d+)', last_search_observation)
                end_match = re.search(r'"end_line":\s*(\d+)', last_search_observation)
                s_line = int(start_match.group(1)) if start_match else 1
                e_line = int(end_match.group(1)) if end_match else 50
                return AgentLLMResponse(
                    tool_calls=[
                        ToolCall(
                            tool=ToolName.READ_FILE,
                            arguments={
                                "path": top_path,
                                "start_line": s_line,
                                "end_line": min(e_line, s_line + 49),
                            },
                        )
                    ]
                )

        # Step C: Formulate final answer referencing discovered source IDs
        discovered_source_ids: list[str] = []
        for msg in messages:
            if msg.content:
                sids = re.findall(r'"source_id":\s*"([^"]+)"', msg.content)
                discovered_source_ids.extend(sids)
        unique_source_ids = list(dict.fromkeys(discovered_source_ids))

        citations_str = f" ({', '.join(unique_source_ids)})" if unique_source_ids else ""
        return AgentLLMResponse(
            final_text=(
                f"[MOCK AGENT] Based on iterative repository investigation, here is the answer to '{question}':\n\n"
                f"The repository includes relevant configurations and definitions identified across "
                f"the inspected files. Consult the verified citations{citations_str} for exact line ranges."
            )
        )

    def _generate_from_prompt_string(self, prompt: str) -> AgentLLMResponse:
        """Heuristic fallback when receiving a raw prompt string."""
        question_match = re.search(r"User Question:\s*(.*?)(?:\n\nOutput your JSON decision:|$)", prompt, re.DOTALL)
        question = question_match.group(1).strip() if question_match else "repository code"

        if "Tool 'search_code'" not in prompt:
            return AgentLLMResponse(
                tool_calls=[ToolCall(tool=ToolName.SEARCH_CODE, arguments={"query": question, "top_k": 5})]
            )
        if "Tool 'read_file'" not in prompt:
            path_match = re.search(r'"path":\s*"([^"]+)"', prompt)
            top_path = path_match.group(1) if path_match else "README.md"
            return AgentLLMResponse(
                tool_calls=[ToolCall(tool=ToolName.READ_FILE, arguments={"path": top_path, "start_line": 1, "end_line": 50})]
            )

        source_ids = re.findall(r'"source_id":\s*"([^"]+)"', prompt)
        unique_source_ids = list(dict.fromkeys(source_ids))
        citations_str = f" ({', '.join(unique_source_ids)})" if unique_source_ids else ""
        return AgentLLMResponse(
            final_text=(
                f"[MOCK AGENT] Based on iterative repository investigation, here is the answer to '{question}':\n\n"
                f"The repository includes relevant configurations and definitions identified across "
                f"the inspected files. Consult the verified citations{citations_str} for exact line ranges."
            )
        )


def get_agent_llm_service(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> AgentLLMService:
    """Factory to instantiate the configured AgentLLMService implementation."""
    active_provider = (provider or settings.llm_provider).lower().strip()

    if active_provider == "gemini":
        from app.services.gemini_agent_llm import GeminiAgentLLMService

        return GeminiAgentLLMService(api_key=api_key, model=model)

    if active_provider == "ollama":
        from app.services.ollama_agent_llm import OllamaAgentLLMService

        return OllamaAgentLLMService(base_url=base_url, model=model)

    return MockAgentLLMService()
