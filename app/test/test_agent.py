import asyncio
import os

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


transport = StdioTransport(
    command="python",
    args=["-m", "app.ai.my_server"],
    env={**os.environ}
)

mcp = Client(transport)


async def main():

    async with mcp:

        tools = await mcp.list_tools()

        print("Available MCP tools:")

        for tool in tools:
            print(f"- {tool.name}")
            print(f"  {tool.description}")


if __name__ == "__main__":
    asyncio.run(main())