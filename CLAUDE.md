# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fipsy is a Python CLI for IPFS content sharing and discovery on local networks. It wraps the `ipfs` CLI binary to enable decentralized file sharing: scanning peers, publishing directories under IPNS keys, and creating discovery indexes.

## Tech Stack

- **Python 3.13+**, **Click** (CLI framework), **uv** (package manager), **hatchling** (build)
- External dependency: IPFS CLI binary must be installed and daemon running

## Commands

```bash
uv sync                # Install dependencies
uv run fipsy --help    # Run CLI
uv build               # Build distribution
```

No test suite or linter is currently configured.

## Architecture

Entry point: `fipsy.main:cli` (defined in `pyproject.toml`)

```
fipsy/
├── main.py       # Click group definition, registers subcommands
├── commands.py   # Subcommands (scan, add, index, publish) + business logic
├── ipfs.py       # Pure wrappers around `ipfs` CLI binary (no business logic)
└── db.py         # SQLite storage for discovered IPNS keys
```

**`ipfs.py`** — Stateless wrapper layer. All IPFS interaction goes through `run_ipfs()` which calls `subprocess.run`. Functions: daemon management, swarm peers, cat, key operations, add, name publish, name resolve, pin add/ls.

**`db.py`** — SQLite storage at `~/.config/fipsy/discovered.db`. Schema:
```sql
discovered (
    node_id TEXT NOT NULL,    -- peer's node ID
    ipns_key TEXT NOT NULL,   -- IPNS key (= node_id for index, else key hash)
    name TEXT,                -- NULL for peer index, else key name
    PRIMARY KEY (node_id, ipns_key)
)
```

**`commands.py`** — Business logic layer. Uses `ThreadPoolExecutor` for concurrent peer scanning and IPNS resolution. Generates JSON + HTML index files in a temp directory for the `publish` command. Filters out "self" key from published indexes.

**Key flow — `scan`**: swarm_peers → concurrent `cat /ipns/{peer}/index.json` for each peer → concurrent `name resolve --recursive` for each discovered IPNS key → save to SQLite → display resolved CIDs. Use `--pin` to pin discovered content.

**Key flow — `index`**: list local keys + query SQLite for discovered keys → check pinned status by resolving IPNS keys and checking against `ipfs pin ls`.

**Key flow — `publish`**: list keys → add each directory from cwd → create temp index (JSON+HTML) → add to IPFS → publish under "self" IPNS key.

## Conventions

- IPNS records use 1-minute TTL, RSA-2048 keys
- Directory names are used as IPNS key names
- `DEFAULT_CAT_TIMEOUT = 5s` for fetching peer content
- `DEFAULT_RESOLVE_TIMEOUT = 10s` for IPNS resolution (DHT lookups are slow)
- Discovered keys stored in `~/.config/fipsy/discovered.db`
- Pinned status is inferred from IPFS at runtime, not stored in DB
