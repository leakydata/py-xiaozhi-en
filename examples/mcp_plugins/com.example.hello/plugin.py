"""An example external MCP plugin. It has no third-party dependencies, so it can be copied straight into your own mcp_plugins/ directory."""


def register(host):
    @host.tool(
        name="example.hello",
        description="Say hello. The name argument is optional. Useful for checking that an external MCP plugin loaded.",
        props=[{"name": "name", "type": "string", "default": "world"}],
    )
    async def hello(args):
        name = (args or {}).get("name") or "world"
        return f"Hello, {name}! (from the external plugin com.example.hello)"

    # optional: the read-only configuration
    cfg = host.get("config_readonly")
    log = host.get("logger")
    if log and cfg is not None:
        log.debug("[example.hello] got config_readonly")
