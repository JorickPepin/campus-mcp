# Campus Coach MCP Server

[![CI](https://github.com/JorickPepin/campus-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/JorickPepin/campus-mcp/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Unofficial [MCP](https://modelcontextprotocol.io) server for the [Campus Coach](https://www.campus.coach) running/trail training platform. It lets any MCP client (Claude Desktop, Claude Code, ...) read your training plan, your pace references and your athlete profile.

> [!WARNING]
>
> Not affiliated with Campus Coach. For personal use only. Uses the same private API as their web app; it may break without notice.

## Tools

| Tool | What it returns |
|------|-----------------|
| `get_athlete_profile` | Gender, age, runner type, target mileage, experience |
| `get_athlete_paces` | Current pace references (VMA, thresholds, fundamental endurance, race pace...), in seconds per km |
| `get_training_calendar` | Training weeks between two ISO dates (`YYYY-MM-DD`): sessions with planned vs actual distance/duration, completion datetime and source activity id (Strava, Garmin...) when done. Without arguments, the whole currently active plan. `include_zones=True` adds the per-session pace-zone breakdown |

The raw API responses are aggressively pruned (nutrition recipes, coach advice, exercise block trees are dropped): a week goes from ~150 KB to a few KB.

## Setup (one time)

There is no server to start or keep running: your MCP client (Claude Desktop, Claude Code, ...) spawns it automatically in the background when a conversation needs it, and stops it when you quit. No need to clone anything either: [uv](https://docs.astral.sh/uv/) installs and runs the server straight from GitHub (and fetches a suitable Python if needed).

**1. Authenticate:**

```bash
uvx --from git+https://github.com/JorickPepin/campus-mcp campus-mcp-auth
```

You'll be prompted for your Campus email and password. They are only used to log in: what gets saved to `~/.campus-mcp/tokens.json` is the API token pair, which the server refreshes on its own afterwards. Your password never touches the disk or your MCP client config.

To check later that the saved tokens still work: `campus-mcp-auth --verify`.

**2. Register the server in your MCP client** — no credentials needed:

### Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "campus": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/JorickPepin/campus-mcp", "campus-mcp"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add campus -- uvx --from git+https://github.com/JorickPepin/campus-mcp campus-mcp
```

### VS Code (GitHub Copilot)

Copilot's agent mode picks up MCP servers from `.vscode/mcp.json` (per project) or your user-level `mcp.json` (run **MCP: Open User Configuration** from the command palette):

```json
{
  "servers": {
    "campus": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/JorickPepin/campus-mcp", "campus-mcp"]
    }
  }
}
```

### Other clients

Any MCP client that supports **stdio** servers (Cursor, Windsurf, LM Studio, ...) works the same way: command `uvx`, args `--from git+https://github.com/JorickPepin/campus-mcp campus-mcp`.

### Alternative: credentials as environment variables

If you'd rather not keep tokens on disk (or you juggle several Campus accounts), skip `campus-mcp-auth` and pass `CAMPUS_EMAIL` and `CAMPUS_PASSWORD` in the server's `env` block instead. When both are set they take precedence over the token file, and the token file is left untouched. In VS Code you can avoid plain-text credentials with an `inputs` block, which prompts on first use and stores them securely:

```json
{
  "inputs": [
    { "id": "campus-email", "type": "promptString", "description": "Campus email" },
    { "id": "campus-password", "type": "promptString", "description": "Campus password", "password": true }
  ],
  "servers": {
    "campus": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/JorickPepin/campus-mcp", "campus-mcp"],
      "env": {
        "CAMPUS_EMAIL": "${input:campus-email}",
        "CAMPUS_PASSWORD": "${input:campus-password}"
      }
    }
  }
}
```

## Example prompts

- **Campus vs Strava** — combine with a Strava MCP server.
  - 🇫🇷 *"Croise mon plan Campus de cette semaine avec mes activités Strava réelles. Est-ce que j'ai respecté mes allures cibles ?"*
  - 🇬🇧 *"Cross-check this week's Campus plan against my actual Strava activities. Did I hit my target paces?"*
- **Smart scheduling** — combine with calendar + weather tools.
  - 🇫🇷 *"Planifie mes séances Campus de la semaine dans mon agenda, en évitant la pluie et les créneaux déjà occupés."*
  - 🇬🇧 *"Schedule this week's Campus sessions in my calendar, avoiding rain and time slots already taken."*
- **Plan adjustment**
  - 🇫🇷 *"J'ai une tension au tendon d'Achille. Lis mon plan Campus de la semaine et dis-moi comment l'adapter."*
  - 🇬🇧 *"My Achilles tendon feels tight. Read this week's Campus plan and tell me how to adapt it."*
- **Fuel logistics**
  - 🇫🇷 *"Analyse ma sortie longue du week-end et ajoute la nutrition nécessaire à ma liste de courses."*
  - 🇬🇧 *"Analyze my weekend long run and add the nutrition I need to my grocery list."*

## Troubleshooting

**"Failed to spawn process: No such file or directory"** — your MCP client can't find `uvx` because it doesn't inherit your shell's `PATH`. Run `which uvx` and put the full path (e.g. `/Users/you/.local/bin/uvx`) in the `command` field.

**"Saved tokens were rejected"** — the refresh token expired or was revoked (e.g. you logged out everywhere). Re-run `campus-mcp-auth`.

**Slow first start** — the first `uvx` invocation downloads and caches the package; later starts are instant. To pick up a new version of this server, run `uv cache prune` or reinstall.

**Logs** — Claude Desktop writes the server's stderr to `~/Library/Logs/Claude/mcp-server-campus.log` (macOS) or `%APPDATA%\Claude\logs\` (Windows).

## Development

Work from a clone and point your MCP client at it instead of GitHub: command `uv`, args `run --directory /path/to/campus-mcp campus-mcp`.

```bash
make install      # sync deps, including dev tooling
make qa           # everything CI runs: format check, lint, mypy, tests
make fmt          # format and autofix
make test         # unit tests only (JSON pruning, token store)
make inspector    # MCP Inspector against the local server
make help         # all targets
```

`make` is a convenience wrapper; every target is a plain `uv run` command if you
prefer typing them out. Authenticate locally with `uv run campus-mcp-auth`
(or `--verify`).

The token file location can be overridden with the `CAMPUS_TOKEN_FILE` environment variable (handy for testing against a second account).

## License

MIT, see [LICENSE](LICENSE). Not affiliated with, endorsed by, or supported by Campus Coach.
