
import os
import json
from pathlib import Path
from dotenv import load_dotenv

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

transport = StdioTransport(
    command="python",
    args=["-m", "app.my_server"],
    env={**os.environ}
)

mcp = Client(transport)


async def ask(question: str):

    async with mcp:

        # 1. Get tools from MCP server
        mcp_tools = await mcp.list_tools()

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

            result = await mcp.call_tool(
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
    question = input("Ask: ")

    answer = asyncio.run(
        ask(question)
    )

    print("\nAnswer:")
    print(answer)   