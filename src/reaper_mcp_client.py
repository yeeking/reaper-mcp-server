import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from contextlib import AsyncExitStack

SERVER_URL = "http://127.0.0.1:8000/mcp"  # adjust path if needed

async def main():
    stack = AsyncExitStack()
    await stack.__aenter__()  # enter the AsyncExitStack
    try:
        # Enter the transport
        read_stream, write_stream, _ = await stack.enter_async_context(
            streamablehttp_client(url=SERVER_URL)
        )
        # Enter the MCP client session
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

        # Initialise session (may be required)
        await session.initialize()

        # List tools
        tools_response = await session.list_tools()
        print("Available tools:")
        for tool in tools_response.tools:
            print(f"  • {tool.name} — {tool.description}")

        # Example call: ask user which tool to run
        tool_name = input("Enter the tool name to call: ").strip()
        args = {}
        if tool_name == "create_track":
            args["index"] = int(input("index: "))
            args["want_defaults"] = input("want_defaults (true/false): ").lower() == "true"

        result = await session.call_tool(tool_name, arguments=args)
        print("Result:", result)

    finally:
        await stack.aclose()

if __name__ == "__main__":
    asyncio.run(main())
