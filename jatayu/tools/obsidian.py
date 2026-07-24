"""Obsidian integration — read, write, search, and manage vault notes.

Uses the Obsidian Local REST API plugin (http://127.0.0.1:27123).
Requires OBSIDIAN_API_KEY in .env and the plugin installed in Obsidian.
"""

from __future__ import annotations

import os

import httpx

from jatayu.tools import Tool, ToolParam, ToolRegistry

OBSIDIAN_BASE = "https://127.0.0.1:27124"


def _headers() -> dict:
    api_key = os.getenv("OBSIDIAN_API_KEY", "").strip()
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.olrapi.note+json, application/json",
    }


def _is_configured() -> bool:
    return bool(os.getenv("OBSIDIAN_API_KEY", "").strip())


def _is_running() -> bool:
    """Check if Obsidian REST API is reachable."""
    try:
        with httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0), verify=False) as client:
            resp = client.get(f"{OBSIDIAN_BASE}/", headers=_headers())
            return resp.status_code == 200
    except Exception:
        return False


# ── Tool Handlers ──


def obsidian_read_note(path: str) -> str:
    """Read a note's markdown content from the vault."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"

    # Normalize path
    if not path.endswith(".md"):
        path += ".md"

    try:
        with httpx.Client(timeout=10, verify=False) as client:
            resp = client.get(
                f"{OBSIDIAN_BASE}/vault/{path}",
                headers=_headers(),
            )

            if resp.status_code == 404:
                return f"Note not found: {path}"

            resp.raise_for_status()

            # The API returns JSON with content field or plain markdown
            content_type = resp.headers.get("content-type", "")
            if "json" in content_type:
                data = resp.json()
                content = data.get("content", resp.text)
            else:
                content = resp.text

        return f"📄 **{path}**\n\n{content}"

    except httpx.ConnectError:
        return "⚠️ Obsidian not running — open Obsidian and ensure Local REST API plugin is enabled"
    except Exception as e:
        return f"⚠️ Obsidian error: {e}"


def obsidian_write_note(path: str, content: str) -> str:
    """Create or overwrite a note in the vault."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"

    if not path.endswith(".md"):
        path += ".md"

    try:
        with httpx.Client(timeout=10, verify=False) as client:
            resp = client.put(
                f"{OBSIDIAN_BASE}/vault/{path}",
                headers={
                    **_headers(),
                    "Content-Type": "text/markdown",
                },
                content=content,
            )
            resp.raise_for_status()

        return f"✅ Note saved: {path}"

    except httpx.ConnectError:
        return "⚠️ Obsidian not running — open Obsidian and ensure Local REST API plugin is enabled"
    except Exception as e:
        return f"⚠️ Obsidian error: {e}"


def obsidian_search(query: str) -> str:
    """Search for notes in the Obsidian vault."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"

    try:
        with httpx.Client(timeout=10, verify=False) as client:
            resp = client.post(
                f"{OBSIDIAN_BASE}/search/simple/",
                headers=_headers(),
                params={"query": query},
            )

            # Fallback: try query parameter approach
            if resp.status_code >= 400:
                resp = client.post(
                    f"{OBSIDIAN_BASE}/search/",
                    headers={
                        **_headers(),
                        "Content-Type": "application/json",
                    },
                    json={"query": query},
                )

            resp.raise_for_status()
            results = resp.json()

        if not results:
            return f"No notes found matching '{query}'"

        if isinstance(results, list):
            lines = [f"Found {len(results)} result(s) for '{query}':\n"]
            for r in results[:15]:
                if isinstance(r, dict):
                    filename = r.get("filename", r.get("path", str(r)))
                    matches = r.get("matches", [])
                    lines.append(f"  • {filename}")
                    if matches:
                        for m in matches[:2]:
                            ctx = m.get("context", m.get("match", ""))
                            if ctx:
                                lines.append(f"    ...{ctx[:80]}...")
                else:
                    lines.append(f"  • {r}")
            return "\n".join(lines)

        return str(results)

    except httpx.ConnectError:
        return "⚠️ Obsidian not running — open Obsidian and ensure Local REST API plugin is enabled"
    except Exception as e:
        return f"⚠️ Obsidian error: {e}"


def obsidian_list_files(folder: str = "/") -> str:
    """List files and folders in the Obsidian vault."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"

    try:
        with httpx.Client(timeout=10, verify=False) as client:
            resp = client.get(
                f"{OBSIDIAN_BASE}/vault/",
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        files = data if isinstance(data, list) else data.get("files", [])

        # Filter by folder if specified
        if folder and folder != "/":
            folder = folder.strip("/")
            files = [f for f in files if str(f).startswith(folder)]

        if not files:
            return f"No files found in '{folder}'"

        lines = [f"Vault contents ({len(files)} items):\n"]
        for f in files[:30]:
            name = f if isinstance(f, str) else f.get("path", str(f))
            lines.append(f"  📄 {name}")

        if len(files) > 30:
            lines.append(f"\n  ...and {len(files) - 30} more")

        return "\n".join(lines)

    except httpx.ConnectError:
        return "⚠️ Obsidian not running — open Obsidian and ensure Local REST API plugin is enabled"
    except Exception as e:
        return f"⚠️ Obsidian error: {e}"


def obsidian_daily_note() -> str:
    """Get or create today's daily note."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"

    try:
        with httpx.Client(timeout=10, verify=False) as client:
            # Try the periodic notes endpoint
            resp = client.get(
                f"{OBSIDIAN_BASE}/periodic/daily/",
                headers=_headers(),
            )

            if resp.status_code == 404:
                # Create daily note
                resp = client.post(
                    f"{OBSIDIAN_BASE}/periodic/daily/",
                    headers=_headers(),
                )

            if resp.status_code >= 400:
                # Fallback: try reading a date-named file
                from datetime import date
                today = date.today().isoformat()
                resp = client.get(
                    f"{OBSIDIAN_BASE}/vault/{today}.md",
                    headers=_headers(),
                )

                if resp.status_code == 404:
                    return f"No daily note found for {today}. Create one in Obsidian or ask me to write one."

            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "json" in content_type:
                data = resp.json()
                content = data.get("content", resp.text)
            else:
                content = resp.text

        return f"📅 **Daily Note**\n\n{content}"

    except httpx.ConnectError:
        return "⚠️ Obsidian not running — open Obsidian and ensure Local REST API plugin is enabled"
    except Exception as e:
        return f"⚠️ Obsidian error: {e}"


def obsidian_update_me_note(fact: str) -> str:
    """Update the Me.md note with personal information."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"
    
    path = "Me.md"
    try:
        # First try to read existing
        existing = ""
        with httpx.Client(timeout=10, verify=False) as client:
            resp = client.get(f"{OBSIDIAN_BASE}/vault/{path}", headers=_headers())
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "json" in content_type:
                    existing = resp.json().get("content", resp.text)
                else:
                    existing = resp.text
            
            # Append the new fact
            new_content = existing + f"\n- {fact}" if existing else f"# Me\n\n- {fact}"
            
            put_resp = client.put(
                f"{OBSIDIAN_BASE}/vault/{path}",
                headers={**_headers(), "Content-Type": "text/markdown"},
                content=new_content,
            )
            put_resp.raise_for_status()
        return f"✅ Saved to Me.md: {fact}"
    except Exception as e:
        return f"⚠️ Failed to update Me.md: {e}"


def obsidian_create_person(name: str, details: str) -> str:
    """Create or update a person note in Obsidian."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"
    
    path = f"People/{name}.md"
    try:
        with httpx.Client(timeout=10, verify=False) as client:
            # Check if exists
            resp = client.get(f"{OBSIDIAN_BASE}/vault/{path}", headers=_headers())
            existing = ""
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                existing = resp.json().get("content", resp.text) if "json" in content_type else resp.text
            
            new_content = existing + f"\n- {details}" if existing else f"# {name}\n\n- {details}"
            
            put_resp = client.put(
                f"{OBSIDIAN_BASE}/vault/{path}",
                headers={**_headers(), "Content-Type": "text/markdown"},
                content=new_content,
            )
            put_resp.raise_for_status()
        return f"✅ Person note updated: People/{name}.md"
    except Exception as e:
        return f"⚠️ Failed to update person note: {e}"


def obsidian_create_project(name: str, details: str) -> str:
    """Create or update a project note in Obsidian."""
    if not _is_configured():
        return "⚠️ OBSIDIAN_API_KEY not set in .env"
    
    path = f"Projects/{name}.md"
    try:
        with httpx.Client(timeout=10, verify=False) as client:
            # Check if exists
            resp = client.get(f"{OBSIDIAN_BASE}/vault/{path}", headers=_headers())
            existing = ""
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                existing = resp.json().get("content", resp.text) if "json" in content_type else resp.text
            
            new_content = existing + f"\n- {details}" if existing else f"# {name}\n\n- {details}"
            
            put_resp = client.put(
                f"{OBSIDIAN_BASE}/vault/{path}",
                headers={**_headers(), "Content-Type": "text/markdown"},
                content=new_content,
            )
            put_resp.raise_for_status()
        return f"✅ Project note updated: Projects/{name}.md"
    except Exception as e:
        return f"⚠️ Failed to update project note: {e}"


# ── Registration ──

def register(registry: ToolRegistry) -> None:
    """Register all Obsidian tools."""
    registry.register(Tool(
        name="obsidian_read_note",
        description="Read a note from the Obsidian vault by its file path. Use when the user wants to read a specific note.",
        handler=obsidian_read_note,
        params=[
            ToolParam(name="path", type="string", description="Path to the note in the vault, e.g. 'Daily/2024-01-15' or 'Projects/MyProject'"),
        ],
    ))

    registry.register(Tool(
        name="obsidian_write_note",
        description="Create or overwrite a note in the Obsidian vault. Use when the user wants to save, create, or update a note in Obsidian.",
        handler=obsidian_write_note,
        params=[
            ToolParam(name="path", type="string", description="Path for the note, e.g. 'Ideas/NewIdea'"),
            ToolParam(name="content", type="string", description="Markdown content for the note"),
        ],
    ))

    registry.register(Tool(
        name="obsidian_search",
        description="Search for notes in the Obsidian vault. Use when the user wants to find notes by keyword.",
        handler=obsidian_search,
        params=[
            ToolParam(name="query", type="string", description="Search query text"),
        ],
    ))

    registry.register(Tool(
        name="obsidian_list_files",
        description="List files and folders in the Obsidian vault. Use when the user wants to browse their vault structure.",
        handler=obsidian_list_files,
        params=[
            ToolParam(name="folder", type="string", description="Folder path to list, e.g. '/' for root or 'Projects/'", required=False),
        ],
    ))

    registry.register(Tool(
        name="obsidian_daily_note",
        description="Get or create today's daily note from Obsidian. Use when the user asks about their daily note or today's journal.",
        handler=obsidian_daily_note,
        params=[],
    ))

    registry.register(Tool(
        name="obsidian_update_me_note",
        description="Update the user's personal Me.md note with new facts or preferences.",
        handler=obsidian_update_me_note,
        params=[
            ToolParam(name="fact", type="string", description="The personal fact or preference to record"),
        ],
    ))

    registry.register(Tool(
        name="obsidian_create_person",
        description="Create or update a note for a person in the People directory.",
        handler=obsidian_create_person,
        params=[
            ToolParam(name="name", type="string", description="The person's name"),
            ToolParam(name="details", type="string", description="Details or context about this person"),
        ],
    ))

    registry.register(Tool(
        name="obsidian_create_project",
        description="Create or update a note for a project in the Projects directory.",
        handler=obsidian_create_project,
        params=[
            ToolParam(name="name", type="string", description="The project's name"),
            ToolParam(name="details", type="string", description="Details or context about this project"),
        ],
    ))
