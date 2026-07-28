# campus-mcp

Unofficial [MCP](https://modelcontextprotocol.io) server for the [Campus Coach](https://www.campus.coach) running/trail training platform. It lets any MCP client (Claude Desktop, Claude Code, ...) read your training plan, your pace references and your athlete profile — heavily filtered so the LLM only sees what matters.

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

There is no server to start or keep running: your MCP client (Claude Desktop, Claude Code, ...) spawns it automatically in the background when a conversation needs it, and stops it when you quit. You only need to install it and tell your client where it is.

Requires [uv](https://docs.astral.sh/uv/) (it will fetch a suitable Python if needed).

**1. Get the code:**

```bash
git clone https://github.com/jorickpepin/campus-mcp.git
```

**2. Register it in your MCP client**, with your Campus account credentials as environment variables.

### Claude Desktop

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "campus": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/campus-mcp", "campus-mcp"],
      "env": {
        "CAMPUS_EMAIL": "you@example.com",
        "CAMPUS_PASSWORD": "your-password"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add campus -e CAMPUS_EMAIL=you@example.com -e CAMPUS_PASSWORD=your-password \
  -- uv run --directory /path/to/campus-mcp campus-mcp
```

### VS Code (GitHub Copilot)

Copilot's agent mode picks up MCP servers from `.vscode/mcp.json` (per project) or your user-level `mcp.json` (run **MCP: Open User Configuration** from the command palette). The `inputs` block makes VS Code prompt for your credentials on first use and store them securely, instead of leaving them in plain text:

```json
{
  "inputs": [
    { "id": "campus-email", "type": "promptString", "description": "Campus email" },
    { "id": "campus-password", "type": "promptString", "description": "Campus password", "password": true }
  ],
  "servers": {
    "campus": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/campus-mcp", "campus-mcp"],
      "env": {
        "CAMPUS_EMAIL": "${input:campus-email}",
        "CAMPUS_PASSWORD": "${input:campus-password}"
      }
    }
  }
}
```

### Other clients

Any MCP client that supports **stdio** servers (Cursor, Windsurf, LM Studio, ...) works the same way: command `uv`, args `run --directory /path/to/campus-mcp campus-mcp`, plus the two `CAMPUS_*` environment variables.

## Example prompts

- **Campus vs Strava** — combine with a Strava MCP server.
  - 🇫🇷 *"Croise mon plan Campus de cette semaine avec mes activités Strava réelles. Est-ce que j'ai respecté mes allures cibles ?"*
  - 🇬🇧 *"Cross-check this week's Campus plan against my actual Strava activities. Did I hit my target paces?"*
- **Smart scheduling** — combine with calendar + weather tools.
  - 🇫🇷 *"Planifie mes séances Campus de la semaine dans mon agenda, en évitant la pluie et les les créneaux déjà occupés."*
  - 🇬🇧 *"Schedule this week's Campus sessions in my calendar, avoiding rain and time slots already taken."*
- **Plan adjustment**
  - 🇫🇷 *"J'ai une tension au tendon d'Achille. Lis mon plan Campus de la semaine et dis-moi comment l'adapter."*
  - 🇬🇧 *"My Achilles tendon feels tight. Read this week's Campus plan and tell me how to adapt it."*
- **Fuel logistics**
  - 🇫🇷 *"Analyse ma sortie longue du week-end et ajoute la nutrition nécessaire à ma liste de courses."*
  - 🇬🇧 *"Analyze my weekend long run and add the nutrition I need to my grocery list."*

## Development

```bash
uv run pytest                                # unit tests on the JSON pruning
uv run mcp dev src/campus_mcp/server.py      # MCP Inspector (needs CAMPUS_* env vars)
```
