from __future__ import annotations

from mcp_anythingllm.config import load_config
from mcp_anythingllm.server import create_server


def main() -> None:
    cfg = load_config()
    server = create_server(cfg)
    server.run(
        "streamable-http",
        host=cfg.host,
        port=cfg.port,
        stateless_http=cfg.stateless_http,
        json_response=cfg.json_response,
    )


if __name__ == "__main__":
    main()