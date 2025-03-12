import argparse
import logging
import sys
from functools import partial
from urllib.parse import urlparse

import anyio
import httpx
from pydantic import AnyHttpUrl

from mcp.client.auth.httpx import McpOAuth
from mcp.client.auth.oauth import InMemoryOAuthStore, OAuthClient
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

if not sys.warnoptions:
    import warnings

    warnings.simplefilter("ignore")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("client")


async def receive_loop(session: ClientSession):
    logger.info("Starting receive loop")
    async for message in session.incoming_messages:
        if isinstance(message, Exception):
            logger.error("Error: %s", message)
            continue

        logger.info("Received message from server: %s", message)


async def run_session(read_stream, write_stream):
    async with (
        ClientSession(read_stream, write_stream) as session,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(receive_loop, session)

        logger.info("Initializing session")
        await session.initialize()
        logger.info("Initialized")


async def main(command_or_url: str, args: list[str], env: list[tuple[str, str]]):
    env_dict = dict(env)

    if urlparse(command_or_url).scheme in ("http", "https"):
        # Use SSE client for HTTP(S) URLs
        oauth_client = OAuthClient(
            client_name="mcp-client",
            server_url=AnyHttpUrl(command_or_url),
            redirect_url=AnyHttpUrl("http://localhost:5999/auth"),
            provider=InMemoryOAuthStore(),
        )
        async with httpx.AsyncClient(auth=McpOAuth(oauth_client)) as http:
            async with sse_client(http, command_or_url) as streams:
                await run_session(*streams)
    else:
        # Use stdio client for commands
        server_parameters = StdioServerParameters(
            command=command_or_url, args=args, env=env_dict
        )
        async with stdio_client(server_parameters) as streams:
            await run_session(*streams)


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("command_or_url", help="Command or URL to connect to")
    parser.add_argument("args", nargs="*", help="Additional arguments")
    parser.add_argument(
        "-e",
        "--env",
        nargs=2,
        action="append",
        metavar=("KEY", "VALUE"),
        help="Environment variables to set. Can be used multiple times.",
        default=[],
    )

    args = parser.parse_args()
    anyio.run(partial(main, args.command_or_url, args.args, args.env), backend="trio")


if __name__ == "__main__":
    cli()
