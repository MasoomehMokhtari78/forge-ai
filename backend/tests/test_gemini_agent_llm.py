"""
Unit tests for GeminiAgentLLMService mocking the google-genai SDK.
Validates tool translation, message translation, function call parsing,
unknown tool rejection, and API error handling.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from google.genai import errors, types

from app.schemas.agent import (
    AgentLLMResponse,
    AgentMessage,
    AgentMessageRole,
    ToolCall,
    ToolName,
    get_agent_tool_definitions,
)
from app.services.gemini_agent_llm import (
    GeminiAPIError,
    GeminiAgentLLMService,
    GeminiConfigurationError,
)


def test_tool_definitions_translation_to_genai_schema():
    """ForgeAI tool definitions are correctly translated into GenAI FunctionDeclarations."""
    tools = get_agent_tool_definitions()
    service = GeminiAgentLLMService(api_key="test-key")
    genai_tools = service._build_genai_tools(tools)

    assert len(genai_tools) == 1
    fds = genai_tools[0].function_declarations
    assert len(fds) == 3

    names = [fd.name for fd in fds]
    assert "search_code" in names
    assert "read_file" in names
    assert "list_files" in names

    # Inspect search_code schema
    search_fd = next(fd for fd in fds if fd.name == "search_code")
    assert search_fd.parameters.type == types.Type.OBJECT
    assert "query" in search_fd.parameters.properties
    assert search_fd.parameters.required == ["query"]


def test_message_translation_to_genai_contents():
    """Normalized ForgeAI messages are translated to Gemini Content objects and system instruction."""
    service = GeminiAgentLLMService(api_key="test-key")
    messages = [
        AgentMessage(role=AgentMessageRole.SYSTEM, content="System instructions here."),
        AgentMessage(role=AgentMessageRole.USER, content="User question."),
        AgentMessage(
            role=AgentMessageRole.ASSISTANT,
            content="I will search first.",
            tool_calls=[ToolCall(tool=ToolName.SEARCH_CODE, arguments={"query": "auth"})],
        ),
        AgentMessage(
            role=AgentMessageRole.TOOL,
            tool_name="search_code",
            content='{"result": "found chunk"}',
        ),
    ]

    system_instruction, contents = service._build_contents_and_system(messages)

    assert system_instruction == "System instructions here."
    assert len(contents) == 3

    # Check User
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "User question."

    # Check Model (Assistant)
    assert contents[1].role == "model"
    assert contents[1].parts[0].text == "I will search first."
    assert contents[1].parts[1].function_call.name == "search_code"
    assert contents[1].parts[1].function_call.args == {"query": "auth"}

    # Check Tool response
    assert contents[2].role == "user"
    assert contents[2].parts[0].function_response.name == "search_code"
    assert contents[2].parts[0].function_response.response == {"result": '{"result": "found chunk"}'}


def test_parse_response_with_function_calls():
    """Response containing function calls is parsed into AgentLLMResponse with ToolCalls."""
    mock_fc = SimpleNamespace(name="read_file", args={"path": "src/main.py", "start_line": 1, "end_line": 20})
    mock_response = SimpleNamespace(
        function_calls=[mock_fc],
        candidates=[],
        text=None,
    )

    llm_response = GeminiAgentLLMService._parse_response(mock_response)
    assert len(llm_response.tool_calls) == 1
    assert llm_response.tool_calls[0].tool == ToolName.READ_FILE
    assert llm_response.tool_calls[0].arguments["path"] == "src/main.py"
    assert llm_response.tool_calls[0].arguments["start_line"] == 1
    assert llm_response.tool_calls[0].arguments["end_line"] == 20
    assert llm_response.final_text is None


def test_parse_response_with_unknown_tool_is_safely_ignored():
    """If Gemini requests an unknown tool, it is ignored and not executed."""
    mock_fc = SimpleNamespace(name="execute_python_shell", args={"cmd": "rm -rf"})
    mock_response = SimpleNamespace(
        function_calls=[mock_fc],
        candidates=[],
        text="Trying something unsafe",
    )

    llm_response = GeminiAgentLLMService._parse_response(mock_response)
    assert len(llm_response.tool_calls) == 0
    assert llm_response.final_text == "Trying something unsafe"


def test_parse_response_with_final_text_only():
    """Response with plain text and no function calls returns final_text."""
    mock_response = SimpleNamespace(
        function_calls=None,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(function_call=None, text="The solution is in auth.py.")]
                )
            )
        ],
        text="The solution is in auth.py.",
    )

    llm_response = GeminiAgentLLMService._parse_response(mock_response)
    assert len(llm_response.tool_calls) == 0
    assert llm_response.final_text == "The solution is in auth.py."


async def test_generate_invokes_gemini_aio_client():
    """Calling generate() properly formats call and returns parsed result."""
    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio

    mock_resp = SimpleNamespace(
        function_calls=[
            SimpleNamespace(name="search_code", args={"query": "database connection", "top_k": 5})
        ],
        candidates=[],
        text=None,
    )
    mock_aio.models.generate_content = AsyncMock(return_value=mock_resp)

    service = GeminiAgentLLMService(api_key="valid-test-key", client=mock_client)
    messages = [AgentMessage(role=AgentMessageRole.USER, content="How do we connect to DB?")]

    res = await service.generate(messages=messages)
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == ToolName.SEARCH_CODE
    assert res.tool_calls[0].arguments["query"] == "database connection"

    # Verify call arguments
    mock_aio.models.generate_content.assert_awaited_once()


async def test_generate_wraps_api_error_in_gemini_api_error():
    """Gemini API exceptions are caught and wrapped into GeminiAPIError."""
    from unittest.mock import patch

    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio

    # Simulate API Error
    mock_aio.models.generate_content = AsyncMock(
        side_effect=errors.APIError(code=429, response_json={"error": {"message": "Resource exhausted"}})
    )

    service = GeminiAgentLLMService(api_key="valid-test-key", client=mock_client)
    messages = [AgentMessage(role=AgentMessageRole.USER, content="Hello")]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(GeminiAPIError, match=r"Gemini API error \(429\): Resource exhausted"):
            await service.generate(messages=messages)
