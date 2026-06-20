# ShotGrid MCP server (lean)

A **Model Context Protocol** server that gives LLM agents (Claude Desktop, Claude Code, Cursor, …) full
access to the **ShotGrid / Autodesk Flow Production Tracking** API — through a **small, curated, agent-first
tool surface** instead of a sprawling one.

> ShotGrid is schema-driven, so a handful of **generic CRUD + query tools reach every entity type**. This
> server leans into that: **15 tools, one CRUD family, a `dry_run` safety gate on every write.**

## Why this exists — what we changed vs the existing server
There's already a capable community server (`loonghao/shotgrid-mcp-server`, MIT). We used it heavily, liked
the engineering, but hit three things that hurt an **autonomous agent** specifically. This server is a
deliberate, leaner take that fixes them:

| Problem in the larger server | What we added here |
|---|---|
| **~60 tools with two overlapping CRUD families** (`sg_find`/`find_one_entity`, `sg_create`/`create_entity`, `sg_batch`/`batch_operations`) **plus `*_tool` alias dupes** — bloats the prompt and makes tool selection ambiguous. | **One** CRUD family: `find` / `find_one` / `create` / `update` / `delete` / `revive` / `batch`. No aliases, no duplicates. **15 tools total.** |
| **No write-safety gate** — `delete`/`create`/`update` commit immediately; the only guard is docstring text. | A **`dry_run` parameter on every write** (`create`, `update`, `delete`, `batch`). `dry_run=true` returns exactly what *would* happen and commits nothing. `delete` is also documented as a **reversible retire** (undo with `revive`). |
| **Studio-specific tools baked into the core** (`find_vendor_users`, `find_vendor_versions`, `create_vendor_playlist`) + thin canned-filter wrappers (`find_recent_playlists`, `find_project_playlists`, …) that assume one shop's schema. | **Dropped.** Anything those did is one `find`/`create` call with explicit filters — no hidden site assumptions. |

Net: same 100% reach (it's generic over the schema), a fraction of the tool count, and **safe by default**
for agents that write.

## The 15 tools
**Generic power tools (full reach over every entity type):**
- `find` · `find_one` — query with ShotGrid filters + field projections
- `create` · `update` · `delete` · `revive` — single-entity writes (`delete` = reversible retire)
- `batch` — atomic multi-op create/update/delete

**Schema & discovery (so the agent can learn the site first):**
- `schema_entity_read` — all entity types
- `schema_field_read` — fields + types for one entity type
- `summarize` — server-side aggregation / status roll-ups (no rows pulled)
- `text_search` — global text search across entity types

**High-value helpers (not just a canned filter):**
- `whoami` — connection + server info
- `find_projects` — common entry point
- `download_thumbnail` — pull an entity's thumbnail/filmstrip to disk
- `upload` — attach a file / set a thumbnail / fill a media field

Every write tool takes `dry_run: bool = false`.

## Install
```bash
pip install -r requirements.txt        # fastmcp, shotgun_api3, requests
```

## Configure (credentials)
Create a **Script** in ShotGrid (Admin ▸ Scripts ▸ *+ Add Script*) and set three env vars (or pass them in
your MCP client config):

| var | value |
|---|---|
| `SHOTGRID_URL` | `https://yourstudio.shotgrid.autodesk.com` |
| `SHOTGRID_SCRIPT_NAME` | the Script's name |
| `SHOTGRID_API_KEY` | that Script's **Application Key** |

For local dev you can instead drop them in a `.env` next to `server.py` (gitignored — see `.env.example`).

## Run / wire into a client
```bash
python3 server.py        # stdio transport
```
Claude Code:
```bash
claude mcp add shotgrid -- python3 /path/to/shotgrid-mcp/server.py
```
Claude Desktop / Cursor (`mcpServers` entry):
```json
{
  "mcpServers": {
    "shotgrid": {
      "command": "python3",
      "args": ["/path/to/shotgrid-mcp/server.py"],
      "env": {
        "SHOTGRID_URL": "https://yourstudio.shotgrid.autodesk.com",
        "SHOTGRID_SCRIPT_NAME": "mcp",
        "SHOTGRID_API_KEY": "••••"
      }
    }
  }
}
```

## Examples (what the agent calls)
```python
# every shot In Progress on a project, with assignees
find("Shot",
     [["project","is",{"type":"Project","id":85}], ["sg_status_list","is","ip"]],
     ["code","sg_status_list","task_template"])

# status roll-up without pulling rows
summarize("Task", [["project","is",{"type":"Project","id":85}]],
          [{"field":"id","type":"count"}],
          grouping=[{"field":"sg_status_list","type":"exact","direction":"asc"}])

# preview a write before committing
create("Shot", {"project":{"type":"Project","id":85}, "code":"sh010"}, dry_run=True)
```

## Credits
Built on Autodesk's [`shotgun_api3`](https://github.com/shotgunsoftware/python-api). Inspired by — and a
leaner alternative to — [`loonghao/shotgrid-mcp-server`](https://github.com/loonghao/shotgrid-mcp-server).
Companion to [`ftrack-mcp`](https://github.com/huikku/ftrack-mcp). MIT licensed.
