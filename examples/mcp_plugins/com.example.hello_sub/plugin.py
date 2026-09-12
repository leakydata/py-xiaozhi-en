"""An example external plugin running under the python-subprocess runtime."""


def register(host):
    @host.tool(
        name="example.hello_sub",
        description="Say hello from a subprocess plugin. The name argument is optional.",
        props=[{"name": "name", "type": "string", "default": "world"}],
    )
    async def hello(args):
        name = (args or {}).get("name") or "world"
        return f"Hello, {name}! (from the subprocess plugin com.example.hello_sub)"
