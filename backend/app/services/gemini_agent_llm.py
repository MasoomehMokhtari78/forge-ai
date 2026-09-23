"""
Google Gemini Agent LLM Service implementation using the official google-genai SDK.
"""

import asyncio
import logging
from typing import Any

from google import genai
from google.genai import errors, types
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


class GeminiConfigurationError(Exception):
    """Raised when Gemini credentials or settings are missing or invalid."""
    pass


class GeminiAPIError(Exception):
    """Raised when an error occurs during communication with Gemini API."""
    pass


class GeminiAgentLLMService(AgentLLMService):
    """Provider implementation responsible exclusively for Google Gemini communication."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
        pacing_delay: float = 0.0,
    ) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self._client = client
        self.pacing_delay = pacing_delay
        self._raw_contents: list[types.Content] = []
        self._sent_tool_count: int = 0
        self._current_user_question: str | None = None

    def _get_client(self) -> genai.Client:
        """Lazy initialization of the google-genai Client."""
        if self._client is not None:
            return self._client
        if not self.api_key or not self.api_key.strip():
            raise GeminiConfigurationError(
                "GEMINI_API_KEY is not configured. Please configure the GEMINI_API_KEY environment variable."
            )
        self._client = genai.Client(api_key=self.api_key.strip())
        return self._client

    def reset(self) -> None:
        """Reset internal multi-turn contents state."""
        self._raw_contents = []
        self._sent_tool_count = 0
        self._current_user_question = None

    @staticmethod
    def _convert_schema(schema_dict: dict[str, Any]) -> types.Schema:
        """Recursively convert JSON Schema dict to google.genai types.Schema."""
        type_map = {
            "string": types.Type.STRING,
            "integer": types.Type.INTEGER,
            "number": types.Type.NUMBER,
            "boolean": types.Type.BOOLEAN,
            "object": types.Type.OBJECT,
            "array": types.Type.ARRAY,
        }
        stype = type_map.get(schema_dict.get("type", "object"), types.Type.OBJECT)
        props = None
        if "properties" in schema_dict:
            props = {k: GeminiAgentLLMService._convert_schema(v) for k, v in schema_dict["properties"].items()}
        items = None
        if "items" in schema_dict:
            items = GeminiAgentLLMService._convert_schema(schema_dict["items"])

        return types.Schema(
            type=stype,
            description=schema_dict.get("description"),
            properties=props,
            required=schema_dict.get("required"),
            items=items,
        )

    def _build_genai_tools(self, tools: list[AgentToolDefinition]) -> list[types.Tool]:
        """Translate normalized ForgeAI tool definitions into google-genai types.Tool."""
        declarations: list[types.FunctionDeclaration] = []
        for tool in tools:
            declarations.append(
                types.FunctionDeclaration(
                    name=tool.name.value,
                    description=tool.description,
                    parameters=self._convert_schema(tool.parameters),
                )
            )
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _build_contents_and_system(
        messages: list[AgentMessage],
    ) -> tuple[str | None, list[types.Content]]:
        """Translate normalized ForgeAI messages into Gemini system instruction and Content items."""
        system_parts: list[str] = []
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == AgentMessageRole.SYSTEM:
                if msg.content:
                    system_parts.append(msg.content)
            elif msg.role == AgentMessageRole.USER:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=msg.content or "")],
                    )
                )
            elif msg.role == AgentMessageRole.ASSISTANT:
                parts: list[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                for tc in msg.tool_calls:
                    parts.append(
                        types.Part.from_function_call(
                            name=tc.tool.value,
                            args=tc.arguments,
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
            elif msg.role == AgentMessageRole.TOOL:
                tool_name = msg.tool_name or "unknown_tool"
                # Gemini API expects function responses with role="user"
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": msg.content or ""},
                            )
                        ],
                    )
                )

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    @staticmethod
    def _parse_response(response: Any) -> AgentLLMResponse:
        """Normalize Gemini SDK response into provider-independent AgentLLMResponse."""
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []

        # 1. Parse function_calls attribute if present
        if hasattr(response, "function_calls") and response.function_calls:
            for fc in response.function_calls:
                try:
                    tool_name = ToolName(fc.name)
                    args = dict(fc.args) if fc.args else {}
                    tool_calls.append(ToolCall(tool=tool_name, arguments=args))
                except ValueError:
                    logger.warning("Gemini requested unrecognized tool: %s", getattr(fc, "name", None))

        # 2. Parse candidates and parts for text or unlisted function calls
        if hasattr(response, "candidates") and response.candidates:
            for cand in response.candidates:
                if hasattr(cand, "content") and cand.content and hasattr(cand.content, "parts"):
                    for part in cand.content.parts:
                        if hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            try:
                                t_name = ToolName(fc.name)
                                args = dict(fc.args) if fc.args else {}
                                if not any(tc.tool == t_name and tc.arguments == args for tc in tool_calls):
                                    tool_calls.append(ToolCall(tool=t_name, arguments=args))
                            except ValueError:
                                logger.warning("Gemini candidate requested unrecognized tool: %s", getattr(fc, "name", None))
                        elif hasattr(part, "text") and part.text:
                            text_parts.append(part.text)

        final_text = "".join(text_parts).strip() if text_parts else None
        if not final_text and hasattr(response, "text") and response.text:
            final_text = response.text.strip()

        # Fallback: parse JSON text tool calls if the model output a JSON string
        if not tool_calls and final_text:
            import json
            import re
            cleaned_text = final_text.strip()
            if cleaned_text.startswith("```"):
                cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text)
                cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
            try:
                data = json.loads(cleaned_text)
                if isinstance(data, dict):
                    if data.get("type") == "tool" or "tool" in data or "name" in data:
                        raw_tool = data.get("tool") or data.get("name")
                        raw_args = data.get("arguments", {})
                        t_name = ToolName(raw_tool)
                        tool_calls.append(ToolCall(tool=t_name, arguments=raw_args))
                        final_text = None
                    elif data.get("type") == "final" and "answer" in data:
                        final_text = data["answer"]
            except Exception:
                pass

        return AgentLLMResponse(final_text=final_text, tool_calls=tool_calls)

    async def generate(
        self,
        messages: list[AgentMessage],
        tools: list[AgentToolDefinition] | None = None,
    ) -> AgentLLMResponse:
        """Execute Gemini LLM generation with structured tool definitions."""
        client = self._get_client()
        active_tools = tools if tools is not None else get_agent_tool_definitions()
        genai_tools = self._build_genai_tools(active_tools)

        # Extract system instruction and user question
        system_parts: list[str] = []
        user_question: str = ""
        tool_messages: list[AgentMessage] = []

        for msg in messages:
            if msg.role == AgentMessageRole.SYSTEM and msg.content:
                system_parts.append(msg.content)
            elif msg.role == AgentMessageRole.USER and msg.content and not user_question:
                user_question = msg.content
            elif msg.role == AgentMessageRole.TOOL:
                tool_messages.append(msg)

        system_instruction = "\n\n".join(system_parts) if system_parts else None

        config = types.GenerateContentConfig(
            tools=genai_tools,
            system_instruction=system_instruction,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.1,
        )

        # Multi-turn conversation state management
        if not self._raw_contents or self._current_user_question != user_question:
            self.reset()
            self._current_user_question = user_question
            self._raw_contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_question)],
                )
            ]
            self._sent_tool_count = 0
        else:
            # Append new tool observations
            new_tools = tool_messages[self._sent_tool_count:]
            for tm in new_tools:
                self._raw_contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tm.tool_name or "search_code",
                                response={"result": tm.content or ""},
                            )
                        ],
                    )
                )
            self._sent_tool_count = len(tool_messages)

        if self.pacing_delay > 0:
            await asyncio.sleep(self.pacing_delay)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = await client.aio.models.generate_content(
                    model=self.model,
                    contents=self._raw_contents,
                    config=config,
                )

                # Preserve model candidate content (with thought_signature) in conversation history
                if hasattr(response, "candidates") and response.candidates:
                    cand = response.candidates[0]
                    if hasattr(cand, "content") and cand.content:
                        self._raw_contents.append(cand.content)

                return self._parse_response(response)

            except errors.APIError as exc:
                if exc.code in (429, 503) and attempt < max_retries - 1:
                    delay = 5.0 * (attempt + 1)
                    import re
                    match = re.search(r"Please retry in ([\d\.]+)s", str(getattr(exc, "message", "")))
                    if match:
                        delay = float(match.group(1)) + 1.5
                    logger.warning("Gemini API error (%s); sleeping %.1fs before retry...", exc.code, delay)
                    await asyncio.sleep(delay)
                    continue
                logger.error("Gemini API error (%s): %s", exc.code, exc.message)
                raise GeminiAPIError(f"Gemini API error ({exc.code}): {exc.message}") from exc
            except (httpx.RemoteProtocolError, httpx.ConnectError) as exc:
                if attempt < max_retries - 1:
                    logger.warning("Gemini network error: %s; retrying...", exc)
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise GeminiAPIError(f"Network error communicating with Gemini: {exc}") from exc
            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.exception("Unexpected error communicating with Gemini: %s", exc)
                    raise GeminiAPIError(f"Failed to communicate with Gemini: {exc}") from exc
                await asyncio.sleep(1.5)

        return AgentLLMResponse(final_text="[GEMINI] Investigation concluded.")
