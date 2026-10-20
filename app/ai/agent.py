import os
import json
from pathlib import Path
from dotenv import load_dotenv
from uuid import UUID

from openai import OpenAI
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import asyncio

load_dotenv()


OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "https://router.huggingface.co/v1",
)

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "Qwen/Qwen3.5-9B",
)

HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    raise ValueError("HF_TOKEN environment variable is not set. Please set it in your .env file.")

llm = OpenAI(
    base_url=OPENAI_BASE_URL,
    api_key=HF_TOKEN,
)


def create_mcp_client_with_user(user_id: str | UUID) -> Client:
    """
    Create an MCP client with user_id injected from authenticated session.
    
    This implements the broker/gateway pattern: user_id is extracted from
    the authenticated session context and used to create the MCP server.
    The LLM never sees user_id as a parameter.
    
    Args:
        user_id: The authenticated user's ID from the session/JWT
        
    Returns:
        Configured MCP client with user_id-injected tools
        
    Note:
        This is a simplified implementation. In production, you would:
        1. Have a gateway server that handles authentication
        2. Extract user_id from JWT in the gateway
        3. Spawn MCP server processes with user_id as env var
        4. Use proper IPC/HTTP transport instead of stdio
    """
    # Set user_id as environment variable for the MCP server
    env = {**os.environ, "MCP_USER_ID": str(user_id)}
    
    transport = StdioTransport(
        command="python",
        args=["-m", "app.ai.my_server"],
        env=env,
    )
    
    return Client(transport)


# Legacy single-user client for backward compatibility
transport = StdioTransport(
    command="python",
    args=["-m", "app.ai.my_server"],
    env={**os.environ}
)

mcp = Client(transport)


async def ask(question: str, user_id: str | UUID | None = None):
    """
    Ask a question with optional user_id for multi-tenant isolation.
    
    Args:
        question: The user's question
        user_id: Optional authenticated user ID. If provided, creates
                   a user-aware MCP client. If None, uses legacy single-user mode.
    """
    
    if user_id is not None:
        # Create MCP client with user_id injection
        client = create_mcp_client_with_user(user_id)
        async with client:
            mcp_tools = await client.list_tools()
            return await _ask_with_client(question, mcp_tools, client)
    else:
        # Use legacy single-user client
        async with mcp:
            mcp_tools = await mcp.list_tools()
            return await _ask_with_client(question, mcp_tools, mcp)


async def _ask_with_client(question: str, mcp_tools, client):
    """Internal helper to ask question with given MCP client."""
    
    # 2. Convert MCP tools → OpenAI/Qwen tools
    tools = []

    for tool in mcp_tools:

        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            },
        })

    # 3. Ask Qwen
    response = llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": """
You are an AI assistant for a document RAG system.

When the user asks something that requires information
from the indexed documents, use the appropriate MCP tool.

Do not invent document information.
Use query_document for normal document questions.
Use retrieve_document_context when retrieval inspection
is specifically required.
Use get_document for document metadata.
""",
            },
            {
                "role": "user",
                "content": question,
            },
        ],
        tools=tools,
        tool_choice="auto",
    )

    message = response.choices[0].message

    # 4. No tool required
    if not message.tool_calls:
        return message.content

    # 5. Execute requested MCP tools
    messages = [
        {
            "role": "system",
            "content": "You are a document RAG assistant.",
        },
        {
            "role": "user",
            "content": question,
        },
        message,
    ]

    for tool_call in message.tool_calls:

        name = tool_call.function.name

        arguments = json.loads(
            tool_call.function.arguments
        )

        result = await client.call_tool(
            name,
            arguments,
        )

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": str(result),
        })

    # 6. Give MCP result back to Qwen
    final_response = llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
    )

    return final_response.choices[0].message.content


if __name__ == "__main__":
    import sys
    
    # Check if user_id is provided as argument
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    if user_id:
        print(f"Multi-user mode with user_id: {user_id}")
    else:
        print("Legacy single-user mode (no user_id provided)")
    
    question = input("Ask: ")

    answer = asyncio.run(
        ask(question, user_id)
    )

    print("\nAnswer:")
    print(answer)   