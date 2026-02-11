# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fipsy is a Python CLI for IPFS content sharing and discovery on local networks. It wraps the `ipfs` CLI binary to enable decentralized file sharing: scanning peers, publishing directories under IPNS keys, and creating discovery indexes.

## Tech Stack

- **Python 3.13+**, **Click** (CLI framework), **Textual** (TUI framework), **uv** (package manager), **hatchling** (build)
- External dependency: IPFS CLI binary must be installed and daemon running

## Commands

```bash
uv sync                # Install dependencies
uv run fipsy --help    # Run CLI
uv run fipsy tui       # Launch TUI dashboard
uv build               # Build distribution
```

No test suite or linter is currently configured.

## Architecture

Entry point: `fipsy.main:cli` (defined in `pyproject.toml`)

```
fipsy/
├── main.py       # Click group definition, registers subcommands (incl. `tui`)
├── commands.py   # Subcommands (scan, add, index, publish) + business logic
├── ipfs.py       # Pure wrappers around `ipfs` CLI binary (no business logic)
├── db.py         # SQLite storage for discovered IPNS keys
└── tui/          # Textual TUI dashboard
    ├── app.py    # FipsyApp — main app, tab wiring, key bindings, workers
    ├── screens.py # Modal screens (AddDirectory, Confirm, IpfsError)
    ├── widgets.py # DataTable subclasses (PeerTable, PublishedTable, BrowseTable)
    ├── workers.py # Business logic extracted from commands.py (returns data, no printing)
    └── styles.tcss # Textual CSS theme
```

**`ipfs.py`** — Stateless wrapper layer. All IPFS interaction goes through `run_ipfs()` which calls `subprocess.run`. Functions: daemon management, swarm peers, cat, key operations, add, name publish, name resolve, pin add/ls.

**`db.py`** — SQLite storage at `~/.config/fipsy/discovered.db`. Schema:
```sql
discovered (
    node_id TEXT NOT NULL,    -- peer's node ID
    ipns_name TEXT NOT NULL,  -- IPNS name (= node_id for index, else key hash)
    name TEXT,                -- NULL for peer index, else key name
    PRIMARY KEY (node_id, ipns_name)
)

published (
    path TEXT PRIMARY KEY,    -- absolute path to directory
    key TEXT NOT NULL,        -- local IPFS key name
    added TEXT NOT NULL       -- ISO timestamp when added
)
```

**`commands.py`** — Business logic layer. Uses `ThreadPoolExecutor` for concurrent peer scanning and IPNS resolution. Generates JSON + HTML index files in a temp directory for the `publish` command. Filters out "self" key from published indexes.

**Key flow — `scan`**: swarm_peers → concurrent `cat /ipns/{peer}/index.json` for each peer → concurrent `name resolve --recursive` for each discovered IPNS key → save to SQLite → display resolved CIDs. Use `--pin` to pin discovered content.

**Key flow — `add`**: prompt for name (default: directory basename) → create IPNS key if needed → add directory to IPFS → publish under IPNS key → store path/key in `published` table.

**Key flow — `index`**: list local keys (showing paths from `published` table) + query SQLite for discovered keys → check pinned status by resolving IPNS keys and checking against `ipfs pin ls`. Shows "(index)" for self key.

**Key flow — `publish`**: read `published` table → add each directory to IPFS → publish under its IPNS key → create temp index (JSON+HTML) → add to IPFS → publish under "self" IPNS key.

**`tui/workers.py`** — Same algorithms as `commands.py` but returns dataclasses (`ScanResult`, `PeerEntry`, `PublishResult`, `BrowseEntry`) instead of printing. Iterator-based `scan_peers_iter()` and `publish_all_iter()` yield results as they complete for real-time UI updates.

**`tui/app.py`** — Three-tab TUI (Network, My Content, Browse). Uses `@work(thread=True)` via `run_worker()` to call blocking IPFS operations off the main thread. Results stream to UI via `call_from_thread()`. Key bindings: `s` scan, `a` add, `P` publish, `p` pin, `d` remove, `o` open browser, `r` refresh, `q` quit.

## Conventions

- IPNS records use 1-minute TTL
- Directory basename is default IPNS key name, user prompted to confirm/change
- `DEFAULT_CAT_TIMEOUT = 5s` for fetching peer content
- `DEFAULT_RESOLVE_TIMEOUT = 10s` for IPNS resolution (DHT lookups are slow)
- Discovered keys and published directories stored in `~/.config/fipsy/discovered.db`
- Pinned status is inferred from IPFS at runtime, not stored in DB
- Path handling uses `pathlib.Path` throughout
