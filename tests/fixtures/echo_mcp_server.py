"""Testler icin minik stdio MCP sunucusu (tests/test_mcp_hub.py)."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("echo")


@server.tool()
def echo(text: str) -> str:
    """Metni geri dondurur."""
    return f"echo: {text}"


@server.tool()
def big_text(n: int = 10000) -> str:
    """Uzun metin uretir."""
    return "x" * n


@server.tool()
def delete_item(item_id: str) -> str:
    """Bir ogeyi siler (sahte)."""
    return f"silindi: {item_id}"


if __name__ == "__main__":
    server.run()
