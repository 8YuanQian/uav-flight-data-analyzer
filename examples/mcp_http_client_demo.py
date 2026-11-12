
import asyncio
import logging

from mcp import Client

logging.basicConfig(level=logging.WARNING)


async def main():
    async with Client(
        "http://127.0.0.1:8765/mcp",
        mode="legacy"
    ) as client:

        print("\n[1] MCP Server 连接成功")

        print("\n[2] 开始发现工具")

        tools_result = await client.list_tools()

        # 兼容不同返回结构
        tools = getattr(tools_result, "tools", tools_result)

        print("工具发现完成：", len(tools))

        for tool in tools:
            print(f"名称：{tool.name}")
            print(f"描述：{tool.description}")

        print("\n[3] 准备调用 pind")

        result = await client.call_tool(
            "pind",
            {"message": "Hello MCP"}
        )

        print("\n[4] 工具调用完成")

        for item in result.content:
            if hasattr(item, "text"):
                print("返回结果：", item.text)

        print("是否执行失败：", result.is_error)

        print("\n[5] 测试全部结束")


if __name__ == "__main__":
    asyncio.run(main())
