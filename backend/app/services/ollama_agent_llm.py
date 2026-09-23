"""
Ollama Agent LLM Service implementation communicating with local Ollama HTTP API.
"""

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.agent import (
    AgentLLMResponse,
    AgentMessage,
    AgentMessageRole,
    AgentToolDefinition,
    ToolCall,
    ToolName,
    get_agent_tool_definitions,
)
from app.services.agent_llm import AgentLLMService

logger = logging.getLogger(__name__)


class OllamaConfigurationError(Exception):
    """Raised when Ollama settings or parameters are invalid or missing."""
    pass


class OllamaAPIError(Exception):
    """Raised when an error occurs during communication with Ollama API."""
    pass


class OllamaAgentLLMService(AgentLLMService):
    """Provider implementation communicating with Ollama's local HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        raw_url = settings.ollama_base_url if base_url is None else base_url
        self.base_url = raw_url.rstrip("/") if raw_url else ""
        self.model = settings.ollama_model if model is None else model
        self._client = client
        self.timeout = timeout
        self._owns_client = False

    def _get_client(self) -> httpx.AsyncClient:
        """Return the injected HTTP client or lazily instantiate one."""
        if not self.base_url:
            raise OllamaConfigurationError(
                "Ollama base URL is not configured. Please set OLLAMA_BASE_URL."
            )
        if not self.model:
            raise OllamaConfigurationError(
                "Ollama model is not configured. Please set OLLAMA_MODEL."
            )
        if self._client is not None:
            is_closed = getattr(self._client, "is_closed", False)
            if isinstance(is_closed, bool) and is_closed:
                self._client = httpx.AsyncClient(timeout=self.timeout)
                self._owns_client = True
            return self._client

        self._client = httpx.AsyncClient(timeout=self.timeout)
        self._owns_client = True
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _build_tools(tools: list[AgentToolDefinition]) -> list[dict[str, Any]]:
        """Translate normalized ForgeAI tool definitions into Ollama function calling format."""
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            declarations.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name.value,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return declarations

    @staticmethod
    def _build_messages(messages: list[AgentMessage]) -> list[dict[str, Any]]:
        """Translate normalized ForgeAI messages into Ollama chat messages."""
        chat_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == AgentMessageRole.SYSTEM:
                chat_messages.append({
                    "role": "system",
                    "content": msg.content or "",
                })
            elif msg.role == AgentMessageRole.USER:
                chat_messages.append({
                    "role": "user",
                    "content": msg.content or "",
                })
            elif msg.role == AgentMessageRole.ASSISTANT:
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or "",
                }
                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "function": {
                                "name": tc.tool.value,
                                "arguments": tc.arguments,
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                chat_messages.append(assistant_msg)
            elif msg.role == AgentMessageRole.TOOL:
                chat_messages.append({
                    "role": "tool",
                    "content": msg.content or "",
                })

        return chat_messages

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> AgentLLMResponse:
        """Parse Ollama chat API response into provider-independent AgentLLMResponse."""
        if not isinstance(data, dict):
            return AgentLLMResponse(final_text=str(data) if data else None)

        message = data.get("message", {})
        if not isinstance(message, dict):
            return AgentLLMResponse(final_text=str(message) if message else None)

        tool_calls: list[ToolCall] = []
        content = message.get("content")
        raw_tool_calls = message.get("tool_calls")

        # 1. Parse native Ollama tool_calls
        if isinstance(raw_tool_calls, list):
            for tc in raw_tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {})
                name = fn.get("name")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                try:
                    tool_name = ToolName(name)
                    tool_calls.append(ToolCall(tool=tool_name, arguments=args if isinstance(args, dict) else {}))
                except ValueError:
                    logger.warning("Ollama requested unrecognized tool: %s", name)

        # If native tool calls were parsed, return them immediately
        if tool_calls:
            return AgentLLMResponse(tool_calls=tool_calls, final_text=None)

        final_text = content.strip() if isinstance(content, str) and content.strip() else None

        # 2. Parse recognized Qwen tagged tool calls (<tool_call> or compatibility <tool_response>)
        #
        # NOTE ON <tool_response>:
        # In standard agent architectures, 'tool_response' or 'tool_result' designates the output
        # returned by a tool back to the assistant.
        # However, observed local Qwen models (e.g. qwen2.5-coder:7b) under Ollama sometimes emit
        # <tool_response>{"name": "...", "arguments": {...}}</tool_response> when attempting to
        # invoke a tool after receiving corrective feedback.
        # We support <tool_response> strictly as an assistant tool-call compatibility fallback,
        # but only when the enclosed payload strictly matches the ToolCall schema with a registered
        # tool name and dictionary arguments. This is NOT normal tool-result handling.
        if final_text:
            tagged_tool_calls: list[ToolCall] = []
            tag_pattern = re.compile(
                r"<(tool_call|tool_response)\s*>(.*?)</\1\s*>",
                re.DOTALL,
            )
            for match in tag_pattern.finditer(final_text):
                tag_name = match.group(1)
                tag_body = match.group(2).strip()

                # Strip markdown code fences if wrapped inside the tag
                if tag_body.startswith("```"):
                    tag_body = re.sub(r"^```(?:json)?\s*", "", tag_body)
                    tag_body = re.sub(r"\s*```$", "", tag_body)
                    tag_body = tag_body.strip()

                try:
                    payload = json.loads(tag_body)
                except Exception:
                    logger.warning("Failed to parse JSON inside <%s> tag: %s", tag_name, tag_body[:100])
                    continue

                if not isinstance(payload, dict):
                    continue

                raw_name = payload.get("name")
                raw_args = payload.get("arguments")

                # Strictly require name as string and arguments as dictionary
                if not isinstance(raw_name, str) or not isinstance(raw_args, dict):
                    continue

                try:
                    t_name = ToolName(raw_name)
                    tagged_tool_calls.append(ToolCall(tool=t_name, arguments=raw_args))
                except ValueError:
                    logger.warning(
                        "Tagged <%s> specified unrecognized tool name: %s",
                        tag_name,
                        raw_name,
                    )

            if tagged_tool_calls:
                # Discard conversational preamble so it is not treated as a final answer
                return AgentLLMResponse(tool_calls=tagged_tool_calls, final_text=None)

        # 3. Existing pure JSON fallback & 4. Existing markdown fenced JSON fallback
        if final_text:
            parsed_json = None
            cleaned = final_text.strip()

            # Priority 3: Direct pure JSON check
            if cleaned.startswith("{") and cleaned.endswith("}"):
                try:
                    parsed_json = json.loads(cleaned)
                except Exception:
                    pass

            # Priority 4: Markdown fenced JSON check
            if parsed_json is None:
                fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
                if fence_match:
                    try:
                        parsed_json = json.loads(fence_match.group(1).strip())
                    except Exception:
                        pass

            if isinstance(parsed_json, dict):
                # Format: {"type": "tool", "tool": "...", "arguments": {...}} or {"name": "...", "arguments": {...}}
                if parsed_json.get("type") == "tool" or "tool" in parsed_json or "name" in parsed_json:
                    raw_tool = parsed_json.get("tool") or parsed_json.get("name")
                    raw_args = parsed_json.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except Exception:
                            raw_args = {}
                    try:
                        t_name = ToolName(raw_tool)
                        tool_calls.append(ToolCall(tool=t_name, arguments=raw_args if isinstance(raw_args, dict) else {}))
                        final_text = None
                    except ValueError:
                        logger.warning("Ollama JSON requested unrecognized tool: %s", raw_tool)

                # Format: {"type": "final", "answer": "..."}
                elif parsed_json.get("type") == "final" and "answer" in parsed_json:
                    final_text = str(parsed_json["answer"])

                # Format: {"tool_calls": [...]}
                elif "tool_calls" in parsed_json and isinstance(parsed_json["tool_calls"], list):
                    for tc in parsed_json["tool_calls"]:
                        if not isinstance(tc, dict):
                            continue
                        t_name_str = tc.get("tool") or tc.get("name")
                        t_args = tc.get("arguments", {})
                        if isinstance(t_args, str):
                            try:
                                t_args = json.loads(t_args)
                            except Exception:
                                t_args = {}
                        try:
                            t_name = ToolName(t_name_str)
                            tool_calls.append(ToolCall(tool=t_name, arguments=t_args if isinstance(t_args, dict) else {}))
                        except ValueError:
                            logger.warning("Ollama JSON requested unrecognized tool: %s", t_name_str)
                    if tool_calls:
                        final_text = None

        return AgentLLMResponse(
            tool_calls=tool_calls,
            final_text=final_text,
        )

    async def generate(
        self,
        messages: list[AgentMessage],
        tools: list[AgentToolDefinition] | None = None,
    ) -> AgentLLMResponse:
        """Invoke Ollama local HTTP API (/api/chat) to generate decisions or answers."""
        client = self._get_client()
        active_tools = tools if tools is not None else get_agent_tool_definitions()

        chat_messages = self._build_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        if active_tools:
            payload["tools"] = self._build_tools(active_tools)

        endpoint = f"{self.base_url}/api/chat"

        try:
            response = await client.post(endpoint, json=payload)
        except httpx.ConnectError as exc:
            logger.error("Failed to connect to Ollama at %s: %s", self.base_url, exc)
            raise OllamaAPIError(
                f"Unable to connect to Ollama server at {self.base_url}. "
                f"Ensure Ollama is running locally: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            logger.error("Timeout communicating with Ollama: %s", exc)
            raise OllamaAPIError(
                f"Request to Ollama timed out after {self.timeout}s: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Network error communicating with Ollama: %s", exc)
            raise OllamaAPIError(
                f"Network error communicating with Ollama at {self.base_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            err_msg = response.text
            try:
                err_json = response.json()
                if isinstance(err_json, dict) and "error" in err_json:
                    err_msg = err_json["error"]
            except Exception:
                pass
            logger.error("Ollama API error (HTTP %d): %s", response.status_code, err_msg)
            raise OllamaAPIError(
                f"Ollama API error (HTTP {response.status_code}): {err_msg}"
            )

        try:
            data = response.json()
        except Exception as exc:
            logger.error("Failed to parse Ollama JSON response: %s", exc)
            raise OllamaAPIError(f"Failed to parse Ollama response as JSON: {exc}") from exc

        return self._parse_response(data)
