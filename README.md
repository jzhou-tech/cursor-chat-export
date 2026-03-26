# Cursor Chat Export

This project provides CLI tools to discover and export AI chat data from [Cursor](https://cursor.sh).

> **This fork** adds `export_new.py` to support the **current Cursor storage format** (globalStorage + `cursorDiskKV`). The original `chat.py` is retained for older Cursor versions.

## Storage Format Comparison

Cursor has changed its chat storage layout over time. Choose the right tool based on your Cursor version:

| | Legacy Format (`chat.py`) | New Format (`export_new.py`) |
|---|---|---|
| **Cursor version** | Older versions | Current versions (2025+) |
| **Metadata location** | Per-workspace `state.vscdb` → `ItemTable` → key `workbench.panel.aichat.view.aichat.chatdata` | Per-workspace `state.vscdb` → `ItemTable` → key `composer.composerData` |
| **Content location** | Same DB as metadata | Global `state.vscdb` → `cursorDiskKV` table → keys `bubbleId:<composerId>:<messageId>` |
| **Global DB path (macOS)** | N/A | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` |

Also see [this](https://forum.cursor.com/t/guide-5-steps-exporting-chats-prompts-from-cursor/2825) forum post on this topic.

## Installation

1. Clone the repository:
    ```sh
    git clone https://github.com/jzhou-tech/cursor-chat-export.git
    cd cursor-chat-export
    ```

2. Install the required dependencies:
    ```sh
    pip install -r requirements.txt
    ```

## Usage — New Format (`export_new.py`)

For **current Cursor versions**. No config file needed — paths are auto-detected.

```sh
# List all conversations
python export_new.py list

# Search conversations by keyword
python export_new.py list --search "keyword"

# Export all conversations to Markdown
python export_new.py export --output-dir ./out

# Export a specific conversation by ID
python export_new.py export --id <composerId>

# Export the latest 5 conversations
python export_new.py export --latest 5
```

---

## Usage — Legacy Format (`chat.py`)

For **older Cursor versions**. Requires [config.yml](./config.yml) to set your workspace storage path.

Both the `discover` and `export` commands will work with the configured path by default, but you can also provide a custom path any time.

### Discover Chats
```sh
# Help on usage
./chat.py discover --help

# Discover all chats from all workspaces
./chat.py discover

# Apply text filter
./chat.py discover --search-text "matplotlib"

# Discover all chats from all workspaces at a custom path
./chat.py discover "/path/to/workspaces"
```

### Export Chats
See `./chat.py export --help` for general help. Examples:
```sh
# Help on usage
./chat.py export --help

# Print all chats of the most recent workspace to the command line
./chat.py export

# Export all chats of the most recent workspace as Markdown
./chat.py export --output-dir "/path/to/output"

# Export only the latest chat of the most recent workspace
./chat.py export --latest-tab --output-dir "/path/to/output"

# Export only chat No. 2 and 3 of the most recent workspace
./chat.py export --tab-ids 2,3 --output-dir "/path/to/output"

# Export all chats of a specifc workspace
./chat.py export --output-dir "/path/to/output" "/path/to/workspaces/workspace-dir/state.vscdb"
```
