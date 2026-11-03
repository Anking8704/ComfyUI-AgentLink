"""ComfyUI-AgentLink: an AI agent that builds and runs workflows, in a ComfyUI sidebar and over MCP.

Registers no nodes. Adds the AgentLink sidebar (web/) and the /agentlink/* routes, which only answer
requests from this computer. Model settings, including the API key, live in <user dir>/agentlink/config.json.
"""
import os

try:
    import folder_paths
    from comfy.cli_args import args
    from server import PromptServer
except ImportError:
    # Imported outside ComfyUI, as pytest does with a package's __init__; there is nothing to attach to.
    PromptServer = None

WILDCARD_OR_LOCAL = {"0.0.0.0", "::", "127.0.0.1", "::1", "localhost"}


def _own_address():
    """Where the agent's tools reach this ComfyUI: loopback unless it only listens on a specific address."""
    addresses = [a.strip() for a in (args.listen or "127.0.0.1").split(",")]
    host = "127.0.0.1" if WILDCARD_OR_LOCAL & set(addresses) else addresses[0]
    if ":" in host:
        host = f"[{host}]"
    tls = bool(args.tls_keyfile and args.tls_certfile)
    # With TLS the certificate is usually self-signed, and the call never leaves this machine.
    return f"{'https' if tls else 'http'}://{host}:{args.port}", (False if tls else None)


if PromptServer is not None:
    from .agentlink.client import ComfyClient
    from .agentlink.server import AgentLinkServer, ConfigStore

    base_url, ssl = _own_address()
    AgentLinkServer(
        ComfyClient(base_url, ssl=ssl),
        ConfigStore(os.path.join(folder_paths.get_user_directory(), "agentlink", "config.json")),
    ).add_routes(PromptServer.instance.routes)

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
