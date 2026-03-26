#!/usr/bin/env python3
"""
Export Cursor chat data from the new storage format (globalStorage/state.vscdb).

New Cursor versions store chat data in:
  - Composer metadata: per-workspace state.vscdb -> ItemTable -> 'composer.composerData'
  - Conversation content: global state.vscdb -> cursorDiskKV -> 'bubbleId:<composerId>:<messageId>'

Usage:
  python export_new.py list                          # List all conversations
  python export_new.py list --search "keyword"       # Search conversations
  python export_new.py export --output-dir ./out     # Export all to Markdown
  python export_new.py export --id <composerId>      # Export a specific conversation
  python export_new.py export --latest 5             # Export latest 5 conversations
"""

import sqlite3
import json
import os
import re
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Export Cursor AI chat history (new format)")
console = Console()

CAPABILITY_LABELS = {
    15: "tool_call",
    30: "context",
}


def get_global_db_path() -> Path:
    system = platform.system()
    paths = {
        "Darwin": "~/Library/Application Support/Cursor/User/globalStorage/state.vscdb",
        "Windows": "%APPDATA%/Cursor/User/globalStorage/state.vscdb",
        "Linux": "~/.config/Cursor/User/globalStorage/state.vscdb",
    }
    if system not in paths:
        raise ValueError(f"Unsupported OS: {system}")
    return Path(os.path.expandvars(paths[system])).expanduser()


def get_workspace_storage_path() -> Path:
    system = platform.system()
    paths = {
        "Darwin": "~/Library/Application Support/Cursor/User/workspaceStorage",
        "Windows": "%APPDATA%/Cursor/User/workspaceStorage",
        "Linux": "~/.config/Cursor/User/workspaceStorage",
    }
    if system not in paths:
        raise ValueError(f"Unsupported OS: {system}")
    return Path(os.path.expandvars(paths[system])).expanduser()


def load_composer_metadata() -> dict:
    """Load composer metadata (names, types, modes) from all workspace databases."""
    composers = {}
    ws_path = get_workspace_storage_path()
    if not ws_path.exists():
        return composers

    for db_file in ws_path.glob("*/state.vscdb"):
        try:
            conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT value FROM ItemTable WHERE key = 'composer.composerData'")
            row = cur.fetchone()
            conn.close()
            if not row:
                continue
            data = json.loads(row[0])
            for c in data.get("allComposers", []):
                cid = c.get("composerId", "")
                if cid and cid not in composers:
                    composers[cid] = {
                        "name": c.get("name", ""),
                        "type": c.get("type", ""),
                        "mode": c.get("unifiedMode", ""),
                        "createdAt": c.get("createdAt", 0),
                        "lastUpdatedAt": c.get("lastUpdatedAt", 0),
                    }
        except Exception:
            continue

    return composers


def load_conversations(global_db: Path, composer_id: Optional[str] = None) -> dict:
    """Load all conversations grouped by composerId from the global database."""
    conn = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
    cur = conn.cursor()

    if composer_id:
        cur.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE ?",
            (f"bubbleId:{composer_id}:%",),
        )
    else:
        cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")

    conversations = {}
    for key, val in cur:
        parts = key.split(":", 2)
        if len(parts) < 3:
            continue
        cid = parts[1]

        text_val = val if isinstance(val, str) else val.decode("utf-8")
        try:
            bubble = json.loads(text_val)
        except json.JSONDecodeError:
            continue

        if cid not in conversations:
            conversations[cid] = []
        conversations[cid].append(bubble)

    conn.close()

    for cid in conversations:
        conversations[cid].sort(key=lambda b: b.get("createdAt", ""))

    return conversations


def format_timestamp(ts) -> str:
    """Convert various timestamp formats to readable string."""
    if not ts:
        return ""
    if isinstance(ts, (int, float)):
        if ts > 1e12:
            ts = ts / 1000
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError):
            return str(ts)
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            return ts
    return str(ts)


def get_first_user_message(bubbles: list) -> str:
    """Extract the first user message text from a conversation."""
    for b in bubbles:
        if b.get("type") == 1 and b.get("text"):
            text = b["text"].strip().replace("\n", " ")
            return text[:80] + ("..." if len(text) > 80 else "")
    return ""


def get_conversation_time_range(bubbles: list) -> tuple:
    """Get the earliest and latest timestamps from a conversation."""
    times = [b.get("createdAt", "") for b in bubbles if b.get("createdAt")]
    if not times:
        return ("", "")
    return (min(times), max(times))


def bubble_to_markdown(bubble: dict, include_tools: bool = False) -> Optional[str]:
    """Convert a single bubble to Markdown text. Returns None if no content."""
    btype = bubble.get("type")
    text = bubble.get("text", "") or ""
    cap_type = bubble.get("capabilityType")
    thinking_blocks = bubble.get("allThinkingBlocks", [])

    if btype == 1:
        if not text.strip():
            return None
        return f"## User\n\n{text.strip()}\n"

    if btype == 2:
        parts = []

        if thinking_blocks:
            thinking_text = ""
            for tb in thinking_blocks:
                if isinstance(tb, dict):
                    thinking_text += tb.get("thinking", "") or tb.get("text", "") or ""
                elif isinstance(tb, str):
                    thinking_text += tb
            if thinking_text.strip():
                parts.append(
                    f"<details>\n<summary>Thinking</summary>\n\n{thinking_text.strip()}\n\n</details>\n"
                )

        if text.strip():
            parts.append(text.strip())

        if include_tools:
            tool_results = bubble.get("toolResults", [])
            for tr in tool_results:
                if isinstance(tr, dict):
                    tool_name = tr.get("toolName", tr.get("name", "tool"))
                    result = tr.get("result", tr.get("output", ""))
                    if result:
                        result_preview = str(result)[:500]
                        parts.append(
                            f"**Tool: {tool_name}**\n```\n{result_preview}\n```\n"
                        )

        if not parts:
            return None

        header = "## Assistant"
        if cap_type and cap_type in CAPABILITY_LABELS:
            label = CAPABILITY_LABELS[cap_type]
            if label == "tool_call" and not include_tools:
                return None
            header += f" ({label})"

        return f"{header}\n\n" + "\n\n".join(parts) + "\n"

    return None


def conversation_to_markdown(
    composer_id: str,
    bubbles: list,
    metadata: dict,
    include_tools: bool = False,
) -> str:
    """Convert a full conversation to a Markdown document."""
    meta = metadata.get(composer_id, {})
    name = meta.get("name", "") or composer_id[:12]
    mode = meta.get("mode", "unknown")
    first_ts, last_ts = get_conversation_time_range(bubbles)

    lines = [f"# {name}\n"]
    lines.append(f"- **Composer ID**: `{composer_id}`")
    lines.append(f"- **Mode**: {mode}")
    lines.append(f"- **Messages**: {len(bubbles)}")
    if first_ts:
        lines.append(f"- **Started**: {format_timestamp(first_ts)}")
    if last_ts:
        lines.append(f"- **Last updated**: {format_timestamp(last_ts)}")
    lines.append("\n---\n")

    for bubble in bubbles:
        md = bubble_to_markdown(bubble, include_tools=include_tools)
        if md:
            lines.append(md)

    return "\n".join(lines)


def sanitize_filename(name: str) -> str:
    """Create a safe filename from a string."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("_.")
    return name[:100] if name else "unnamed"


@app.command("list")
def list_chats(
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Filter by keyword in name or first message"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max conversations to show"),
    sort_by: str = typer.Option("time", "--sort", help="Sort by: time, messages, name"),
):
    """List all conversations with summary info."""
    global_db = get_global_db_path()
    if not global_db.exists():
        console.print(f"[red]Global database not found: {global_db}[/red]")
        raise typer.Exit(1)

    console.print("[dim]Loading composer metadata...[/dim]")
    metadata = load_composer_metadata()

    console.print("[dim]Loading conversations (this may take a moment)...[/dim]")
    conversations = load_conversations(global_db)

    items = []
    for cid, bubbles in conversations.items():
        meta = metadata.get(cid, {})
        name = meta.get("name", "")
        mode = meta.get("mode", "")
        first_msg = get_first_user_message(bubbles)
        first_ts, last_ts = get_conversation_time_range(bubbles)
        user_count = sum(1 for b in bubbles if b.get("type") == 1)
        ai_text_count = sum(1 for b in bubbles if b.get("type") == 2 and b.get("text"))

        if search:
            search_lower = search.lower()
            searchable = f"{name} {first_msg} {cid}".lower()
            if search_lower not in searchable:
                continue

        items.append({
            "id": cid,
            "name": name or first_msg[:50] or cid[:12],
            "mode": mode,
            "messages": len(bubbles),
            "user_msgs": user_count,
            "ai_msgs": ai_text_count,
            "first_msg": first_msg,
            "first_ts": first_ts,
            "last_ts": last_ts,
        })

    if sort_by == "messages":
        items.sort(key=lambda x: x["messages"], reverse=True)
    elif sort_by == "name":
        items.sort(key=lambda x: x["name"].lower())
    else:
        items.sort(key=lambda x: x["last_ts"] or "", reverse=True)

    items = items[:limit]

    table = Table(title=f"Cursor Conversations ({len(items)} shown)")
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", style="cyan", max_width=40)
    table.add_column("Mode", style="green", width=8)
    table.add_column("Msgs", justify="right", width=6)
    table.add_column("Last Active", width=22)
    table.add_column("First Message", max_width=50)
    table.add_column("Composer ID", style="dim", width=14)

    for i, item in enumerate(items, 1):
        table.add_row(
            str(i),
            item["name"][:40],
            item["mode"],
            str(item["messages"]),
            format_timestamp(item["last_ts"]),
            item["first_msg"][:50],
            item["id"][:12] + "...",
        )

    console.print(table)


@app.command()
def export(
    output_dir: str = typer.Option("./cursor-chats-export", "--output-dir", "-o", help="Output directory for Markdown files"),
    composer_id: Optional[str] = typer.Option(None, "--id", help="Export a specific conversation by composer ID (partial match OK)"),
    latest: Optional[int] = typer.Option(None, "--latest", "-l", help="Export only the N most recent conversations"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Export conversations matching keyword"),
    include_tools: bool = typer.Option(False, "--include-tools", help="Include tool call results in export"),
    min_messages: int = typer.Option(2, "--min-messages", help="Skip conversations with fewer messages"),
):
    """Export conversations to Markdown files."""
    global_db = get_global_db_path()
    if not global_db.exists():
        console.print(f"[red]Global database not found: {global_db}[/red]")
        raise typer.Exit(1)

    console.print("[dim]Loading metadata...[/dim]")
    metadata = load_composer_metadata()

    if composer_id:
        console.print(f"[dim]Loading conversation {composer_id}...[/dim]")
        conversations = load_conversations(global_db, composer_id)
        if not conversations:
            all_convs = load_conversations(global_db)
            matches = {k: v for k, v in all_convs.items() if composer_id.lower() in k.lower()}
            if matches:
                conversations = matches
            else:
                console.print(f"[red]No conversation found for ID: {composer_id}[/red]")
                raise typer.Exit(1)
    else:
        console.print("[dim]Loading all conversations (this may take a while for large databases)...[/dim]")
        conversations = load_conversations(global_db)

    items = []
    for cid, bubbles in conversations.items():
        if len(bubbles) < min_messages:
            continue

        has_content = any(
            b.get("text") for b in bubbles if b.get("type") in (1, 2)
        )
        if not has_content:
            continue

        if search:
            meta = metadata.get(cid, {})
            name = meta.get("name", "")
            first_msg = get_first_user_message(bubbles)
            searchable = f"{name} {first_msg} {cid}".lower()
            if search.lower() not in searchable:
                continue

        _, last_ts = get_conversation_time_range(bubbles)
        items.append((cid, bubbles, last_ts))

    items.sort(key=lambda x: x[2] or "", reverse=True)

    if latest:
        items = items[:latest]

    if not items:
        console.print("[yellow]No conversations to export.[/yellow]")
        raise typer.Exit(0)

    os.makedirs(output_dir, exist_ok=True)
    console.print(f"\nExporting [bold]{len(items)}[/bold] conversations to [cyan]{output_dir}[/cyan]...\n")

    for i, (cid, bubbles, _) in enumerate(items, 1):
        meta = metadata.get(cid, {})
        name = meta.get("name", "") or get_first_user_message(bubbles)[:50] or cid[:12]

        md_content = conversation_to_markdown(cid, bubbles, metadata, include_tools)

        safe_name = sanitize_filename(name)
        filename = f"{safe_name}_{cid[:8]}.md"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)

        user_count = sum(1 for b in bubbles if b.get("type") == 1)
        console.print(f"  [{i}/{len(items)}] {name[:50]} ({user_count} user msgs) -> {filename}")

    console.print(f"\n[green]Done! Exported {len(items)} conversations to {output_dir}[/green]")


@app.command()
def show(
    composer_id: str = typer.Argument(help="Composer ID to display (partial match OK)"),
    include_tools: bool = typer.Option(False, "--include-tools", help="Include tool call results"),
):
    """Display a single conversation in the terminal."""
    global_db = get_global_db_path()
    if not global_db.exists():
        console.print(f"[red]Global database not found: {global_db}[/red]")
        raise typer.Exit(1)

    metadata = load_composer_metadata()
    conversations = load_conversations(global_db, composer_id)

    if not conversations:
        all_convs = load_conversations(global_db)
        conversations = {k: v for k, v in all_convs.items() if composer_id.lower() in k.lower()}

    if not conversations:
        console.print(f"[red]No conversation found for: {composer_id}[/red]")
        raise typer.Exit(1)

    for cid, bubbles in conversations.items():
        from rich.markdown import Markdown
        md = conversation_to_markdown(cid, bubbles, metadata, include_tools)
        console.print(Markdown(md))


if __name__ == "__main__":
    app()
