from mcp.server import FastMCP

# Initialize the MCP server
mcp = FastMCP("Calculator")

# Define a tool that the AI can call
@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

if __name__ == "__main__":
#   mcp.run()
    # For testing purposes, we can call the tool directly
    result = add_numbers(5, 7)
    print(f"The result of adding 5 and 7 is: {result}")

