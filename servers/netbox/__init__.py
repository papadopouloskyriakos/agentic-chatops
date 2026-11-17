# NetBox API client — wraps netbox MCP tools as Python functions
# Eliminates sequential MCP round-trips for multi-device lookups.
from .client import NetBoxClient

client = NetBoxClient()
