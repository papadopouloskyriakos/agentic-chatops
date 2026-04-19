# servers/ — Code-as-Tool-Orchestrator (G1)
#
# Python wrappers around MCP tool calls for use in Claude Code sessions.
# Instead of making 10 sequential MCP tool calls (each a full context round-trip),
# Claude writes a Python script that imports these modules and chains operations.
#
# Usage from Claude Code:
#   python3 -c "from servers.netbox import client; print(client.get_device('nl-pve01'))"
#
# Each module wraps the corresponding MCP server's tools as simple function calls.
# Source: Anthropic 'Code Execution with MCP' (2025)
