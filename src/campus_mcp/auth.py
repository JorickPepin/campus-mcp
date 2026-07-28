"""Token persistence and one-time authentication CLI (campus-mcp-auth)."""

import argparse
import asyncio
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

DEFAULT_TOKEN_FILE = Path.home() / ".campus-mcp" / "tokens.json"


class TokenStore:
    """Persists the Campus token pair on disk so the server can run without
    credentials. The file is rewritten on every token rotation."""

    def __init__(self, path: Path | None = None) -> None:
        env_path = os.environ.get("CAMPUS_TOKEN_FILE")
        self.path = path or (Path(env_path) if env_path else DEFAULT_TOKEN_FILE)

    def load(self) -> dict[str, str] | None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if (
            not isinstance(data, dict)
            or not data.get("token")
            or not data.get("refreshToken")
        ):
            return None
        return {"token": data["token"], "refreshToken": data["refreshToken"]}

    def save(self, token: str, refresh_token: str) -> None:
        directory = self.path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # os.replace() is only atomic within a single filesystem, so the temp
        # file must live next to the destination (never in /tmp: EXDEV).
        # mkstemp creates it with mode 0600.
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tokens-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"token": token, "refreshToken": refresh_token}, f)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise


async def _login(store: TokenStore) -> None:
    from campus_mcp.client import CampusClient

    email = os.environ.get("CAMPUS_EMAIL") or input("Campus email: ")
    password = os.environ.get("CAMPUS_PASSWORD") or getpass.getpass("Campus password: ")
    client = CampusClient(email=email, password=password, token_store=store)
    try:
        await client.get("/account/user-infos")
    finally:
        await client.close()
    print(f"Authentication OK. Tokens saved to {store.path}")
    print("Your MCP client config no longer needs CAMPUS_EMAIL/CAMPUS_PASSWORD.")


async def _verify(store: TokenStore) -> None:
    from campus_mcp.client import CampusClient

    if store.load() is None:
        sys.exit(f"No tokens found at {store.path}: run campus-mcp-auth first.")
    client = CampusClient(token_store=store)
    try:
        await client.get("/account/user-infos")
    finally:
        await client.close()
    print(f"Tokens at {store.path} are valid.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="campus-mcp-auth",
        description="Authenticate against Campus Coach once and save tokens "
        "locally, so the MCP server can run without credentials.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="check that the saved tokens still work instead of logging in",
    )
    args = parser.parse_args()

    store = TokenStore()
    try:
        asyncio.run(_verify(store) if args.verify else _login(store))
    except Exception as exc:  # noqa: BLE001 - CLI boundary, show a clean error
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
