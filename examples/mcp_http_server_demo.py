from mcp.server import MCPServer

mcp = MCPServer("UAV MCP Server")

@mcp.tool()
def pind(message:str) -> str:
    """input a message return determine message"""
    return f"收到信息: {message}"

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8765,
    )

