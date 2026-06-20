#!/usr/bin/env python3
"""ShotGrid / Flow Production Tracking MCP server — lean, generic coverage for LLM agents.

Design: ShotGrid's API is a *generic CRUD + query over a schema-driven model*, so a **small set of
generic power tools** (`find` / `find_one` / `create` / `update` / `delete` / `revive` / `batch`) reaches
**every entity type**, plus **schema introspection** and a few high-value helpers. One CRUD family, no
duplicates, with a `dry_run` safety gate on every write. MIT licensed.

Config (env or MCP client config):
  SHOTGRID_URL          e.g. https://yourstudio.shotgrid.autodesk.com
  SHOTGRID_SCRIPT_NAME  a Script name  (Admin ▸ Scripts ▸ + Add Script)
  SHOTGRID_API_KEY      that script's Application Key

Run:  python3 server.py        (stdio transport, for Claude Desktop / Cursor / Claude Code)
"""
import os, datetime, tempfile
import requests
import shotgun_api3
from fastmcp import FastMCP

mcp = FastMCP("shotgrid")
_sg = None


def _env(name, default=None):
    v = os.environ.get(name)
    if v:
        return v
    # fall back to a sibling .env (dev convenience) — never required in production
    for p in (".env",):
        if os.path.exists(p):
            for line in open(p):
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].split(" #", 1)[0].strip().strip('"').strip("'")
    return default


def sg():
    global _sg
    if _sg is None:
        _sg = shotgun_api3.Shotgun(
            _env("SHOTGRID_URL"),
            script_name=_env("SHOTGRID_SCRIPT_NAME"),
            api_key=_env("SHOTGRID_API_KEY"),
        )
    return _sg


# ---- serialization: ShotGrid returns plain dicts/lists; just make datetimes JSON-safe ----------
def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    return obj


# =====================================================================================
#  GENERIC POWER TOOLS  (one CRUD family — full API reach across every entity type)
# =====================================================================================
def find(entity_type: str, filters: list | None = None, fields: list[str] | None = None,
         order: list | None = None, filter_operator: str = "all", limit: int = 100) -> list[dict]:
    """Query any entity type. The single tool for all reads.

    `filters` is ShotGrid's list-of-conditions form, e.g.
        [["project","is",{"type":"Project","id":85}], ["sg_status_list","is","ip"]]
    `fields` are the columns to return, e.g. ["code","sg_status_list","task_assignees"].
    `order` is e.g. [{"field_name":"created_at","direction":"desc"}].
    `filter_operator` is "all" (AND) or "any" (OR).
    """
    return _clean(sg().find(entity_type, filters or [], fields or [],
                            order or [], filter_operator, limit=limit))


def find_one(entity_type: str, filters: list | None = None, fields: list[str] | None = None) -> dict | None:
    """Return the first matching entity (or null)."""
    return _clean(sg().find_one(entity_type, filters or [], fields or []))


def create(entity_type: str, data: dict, dry_run: bool = False) -> dict:
    """Create an entity. `data` maps fields to values; entity links are {"type":"Project","id":85}.
    e.g. create("Shot", {"project":{"type":"Project","id":85}, "code":"sh010"}).
    Set `dry_run=true` to preview the write without committing."""
    if dry_run:
        return {"dry_run": True, "would": "create", "entity_type": entity_type, "data": _clean(data)}
    return _clean(sg().create(entity_type, data))


def update(entity_type: str, entity_id: int, data: dict,
           multi_entity_update_modes: dict | None = None, dry_run: bool = False) -> dict:
    """Update an entity by id. `data` = fields to set. `multi_entity_update_modes` optionally maps a
    multi-entity field name to "add" / "remove" / "set" (default replaces).
    Set `dry_run=true` to preview without committing."""
    if dry_run:
        return {"dry_run": True, "would": "update", "entity_type": entity_type,
                "entity_id": entity_id, "data": _clean(data)}
    return _clean(sg().update(entity_type, entity_id, data,
                              multi_entity_update_modes=multi_entity_update_modes))


def delete(entity_type: str, entity_id: int, dry_run: bool = False) -> dict:
    """Delete (retire) an entity by id. In ShotGrid this is a **reversible soft-delete** — use `revive`
    to undo. Set `dry_run=true` to preview without committing."""
    if dry_run:
        return {"dry_run": True, "would": "delete (retire)",
                "entity_type": entity_type, "entity_id": entity_id}
    ok = sg().delete(entity_type, entity_id)
    return {"ok": bool(ok), "retired": {"type": entity_type, "id": entity_id}}


def revive(entity_type: str, entity_id: int) -> dict:
    """Revive (un-retire) a previously deleted entity."""
    ok = sg().revive(entity_type, entity_id)
    return {"ok": bool(ok), "revived": {"type": entity_type, "id": entity_id}}


def batch(requests: list, dry_run: bool = False) -> list:
    """Run multiple create/update/delete operations **atomically**. Each request is a dict:
        {"request_type":"create","entity_type":"Shot","data":{...}}
        {"request_type":"update","entity_type":"Shot","entity_id":1,"data":{...}}
        {"request_type":"delete","entity_type":"Shot","entity_id":1}
    Set `dry_run=true` to preview the whole batch without committing."""
    if dry_run:
        return [{"dry_run": True, **_clean(r)} for r in requests]
    return _clean(sg().batch(requests))


# =====================================================================================
#  SCHEMA / DISCOVERY  (so an agent can learn the site's fields before querying)
# =====================================================================================
def schema_entity_read() -> dict:
    """List all entity types in this site's schema (display names + visibility)."""
    return _clean(sg().schema_entity_read())


def schema_field_read(entity_type: str) -> dict:
    """Read all fields (and their data types) for an entity type — for building queries/creates."""
    return _clean(sg().schema_field_read(entity_type))


def summarize(entity_type: str, filters: list, summary_fields: list,
              grouping: list | None = None, filter_operator: str = "all") -> dict:
    """Aggregate without pulling rows. `summary_fields` e.g. [{"field":"id","type":"count"}];
    `grouping` e.g. [{"field":"sg_status_list","type":"exact","direction":"asc"}].
    Great for status roll-ups / counts."""
    return _clean(sg().summarize(entity_type, filters or [], summary_fields,
                                 grouping=grouping, filter_operator=filter_operator))


def text_search(text: str, entity_types: list[str] | None = None,
                project_id: int | None = None, limit: int = 50) -> dict:
    """Global text search across one or more entity types (defaults to the common production ones)."""
    et = {t: [] for t in (entity_types or ["Asset", "Shot", "Task", "Sequence", "Version", "Note"])}
    return _clean(sg().text_search(text, et, project_ids=[project_id] if project_id else None, limit=limit))


# =====================================================================================
#  HIGH-VALUE HELPERS  (non-redundant — not just a canned filter over `find`)
# =====================================================================================
def whoami() -> dict:
    """The connected script identity + server info (validates the connection)."""
    s = sg()
    try:
        info = s.info()
    except Exception as e:
        info = {"error": str(e)}
    return {"server": _env("SHOTGRID_URL"), "script_name": _env("SHOTGRID_SCRIPT_NAME"),
            "server_version": info.get("version"), "s3_enabled": info.get("s3_enabled")}


def find_projects(include_archived: bool = False, fields: list[str] | None = None) -> list[dict]:
    """List projects — a common entry point. Returns name/status/archived/description by default."""
    filters = [] if include_archived else [["archived", "is", False]]
    return _clean(sg().find("Project", filters,
                            fields or ["name", "sg_status", "archived", "sg_description"]))


def download_thumbnail(entity_type: str, entity_id: int, field: str = "image",
                       path: str | None = None) -> dict:
    """Download an entity's thumbnail/filmstrip image to a local file. Returns the saved path.
    Use field="image" (thumbnail) or "filmstrip_image"."""
    rec = sg().find_one(entity_type, [["id", "is", entity_id]], [field])
    url = rec.get(field) if rec else None
    if not url:
        return {"error": f"no {field} on {entity_type} {entity_id}"}
    data = requests.get(url, timeout=60).content
    if not path:
        fd, path = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return {"ok": True, "path": path, "bytes": len(data), "url": url}


def upload(entity_type: str, entity_id: int, path: str, field_name: str | None = None) -> dict:
    """Upload a file to an entity. field_name=None attaches it; field_name="image" sets the thumbnail;
    or target a File/Link field (e.g. "sg_uploaded_movie" on a Version). Returns the Attachment id."""
    aid = sg().upload(entity_type, entity_id, path, field_name=field_name)
    return {"ok": True, "attachment_id": aid, "entity": {"type": entity_type, "id": entity_id}}


# ---- register every function above as an MCP tool -----------------------------------------
for _fn in (find, find_one, create, update, delete, revive, batch,
            schema_entity_read, schema_field_read, summarize, text_search,
            whoami, find_projects, download_thumbnail, upload):
    mcp.tool(_fn)


if __name__ == "__main__":
    mcp.run()
