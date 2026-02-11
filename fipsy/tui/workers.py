"""Business logic for TUI — returns data instead of printing."""

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from fipsy import db, ipfs
from fipsy.commands import _write_index_html, _write_index_json

MAX_WORKERS = 20
MANY_PEERS_THRESHOLD = 20
FAST_CAT_TIMEOUT = 2.69


@dataclass
class PeerEntry:
    peer_id: str
    name: str
    ipns_name: str
    cid: str | None = None


@dataclass
class ScanResult:
    """Result of scanning a single peer."""

    peer_id: str
    entries: list[PeerEntry] = field(default_factory=list)


@dataclass
class PublishResult:
    key: str
    ipns_name: str
    cid: str | None = None
    error: str | None = None


@dataclass
class BrowseEntry:
    source: str  # "local" or peer_id
    name: str
    ipns_name: str
    pinned: bool = False


def check_ipfs() -> tuple[bool, bool]:
    """Check IPFS status. Returns (installed, daemon_running)."""
    if not ipfs.is_installed():
        return False, False
    return True, ipfs.is_daemon_running()


def start_ipfs_daemon() -> bool:
    """Start the IPFS daemon. Returns True on success."""
    try:
        ipfs.start_daemon()
        return True
    except RuntimeError:
        return False


def _resolve_key(ipns_name: str) -> str | None:
    try:
        return ipfs.name_resolve(ipns_name)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _fetch_peer_index(peer_id: str, cat_timeout: float) -> ScanResult | None:
    """Fetch a single peer's index and resolve its IPNS keys."""
    try:
        raw = ipfs.cat_path(f"/ipns/{peer_id}/index.json", timeout=cat_timeout)
        data = json.loads(raw)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        OSError,
    ):
        return None

    ipns_keys: dict[str, str] = data.get("ipns", {})
    if not ipns_keys:
        return None

    result = ScanResult(peer_id=peer_id)
    with ThreadPoolExecutor(max_workers=min(10, len(ipns_keys))) as pool:
        futures = {
            pool.submit(_resolve_key, key_id): name
            for name, key_id in ipns_keys.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            resolved = future.result()
            cid = resolved.split("/")[-1] if resolved else None
            result.entries.append(
                PeerEntry(
                    peer_id=peer_id,
                    name=name,
                    ipns_name=ipns_keys[name],
                    cid=cid,
                )
            )

    return result


def scan_peers_iter() -> Iterator[ScanResult | int]:
    """Scan peers, yielding results as they complete.

    First yields the total peer count (int), then ScanResult objects.
    """
    peers = ipfs.swarm_peers()
    yield len(peers)

    if not peers:
        return

    many_peers = len(peers) > MANY_PEERS_THRESHOLD
    cat_timeout = FAST_CAT_TIMEOUT if many_peers else ipfs.DEFAULT_CAT_TIMEOUT

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(peers))) as pool:
        futures = {
            pool.submit(_fetch_peer_index, pid, cat_timeout): pid for pid in peers
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                # Save to DB
                db.upsert_discovered(result.peer_id, result.peer_id)
                for entry in result.entries:
                    db.upsert_discovered(
                        result.peer_id, entry.ipns_name, name=entry.name
                    )
                yield result


def pin_cid(cid: str) -> bool:
    """Pin a CID. Returns True on success."""
    try:
        ipfs.pin_add(cid)
        return True
    except subprocess.CalledProcessError:
        return False


def get_published() -> list[dict]:
    """Get all published directories from DB."""
    return db.list_published()


def add_directory(dir_path: str, key_name: str) -> PublishResult:
    """Add a directory to IPFS and publish under an IPNS key."""
    abs_path = Path(dir_path).resolve()

    keys = ipfs.key_list()
    if key_name not in keys:
        ipfs.key_gen(key_name)

    cid = ipfs.add_directory(str(abs_path))
    ipfs.name_publish(cid, key=key_name, ttl="1m")

    keys = ipfs.key_list()
    ipns_name = keys.get(key_name, "")

    db.upsert_published(str(abs_path), key_name)

    return PublishResult(key=key_name, ipns_name=ipns_name, cid=cid)


def remove_published(path: str) -> bool:
    """Remove a published directory from the DB."""
    return db.delete_published(path)


def publish_all_iter() -> Iterator[PublishResult | int]:
    """Publish all directories, yielding results as they complete.

    First yields the total count (int), then PublishResult objects.
    """
    published = db.list_published()
    yield len(published)

    if not published:
        return

    keys = ipfs.key_list()
    published_keys: dict[str, str] = {}

    for entry in published:
        key = entry["key"]
        path = Path(entry["path"])
        ipns_name = keys.get(key)

        if not ipns_name:
            yield PublishResult(key=key, ipns_name="", error="IPNS name not found")
            continue

        if not path.is_dir():
            yield PublishResult(
                key=key, ipns_name=ipns_name, error=f"Directory not found: {path}"
            )
            continue

        try:
            cid = ipfs.add_directory(str(path))
            ipfs.name_publish(cid, key=key, ttl="1m")
            published_keys[key] = ipns_name
            yield PublishResult(key=key, ipns_name=ipns_name, cid=cid)
        except subprocess.CalledProcessError:
            yield PublishResult(key=key, ipns_name=ipns_name, error="Publish failed")

    if not published_keys:
        return

    # Create and publish discovery index
    discovery_dir = Path(tempfile.mkdtemp(prefix="fipsy-index-"))
    try:
        _write_index_json(discovery_dir, published_keys)
        _write_index_html(discovery_dir, published_keys)
        cid = ipfs.add_directory(str(discovery_dir))
        ipfs.name_publish(cid, ttl="1m")
    finally:
        shutil.rmtree(discovery_dir, ignore_errors=True)


def get_browse_entries() -> list[BrowseEntry]:
    """Get all known IPNS keys (local + discovered) for browsing."""
    entries: list[BrowseEntry] = []

    # Local keys
    keys = ipfs.key_list()
    published_paths = {e["key"]: e["path"] for e in db.list_published()}
    for key, ipns_name in keys.items():
        display_name = "(index)" if key == "self" else key
        source = f"local ({published_paths[key]})" if key in published_paths else "local"
        entries.append(BrowseEntry(source=source, name=display_name, ipns_name=ipns_name))

    # Discovered keys
    discovered = db.list_discovered()
    pinned_cids = ipfs.pin_ls()
    for row in discovered:
        name = row["name"] or "(index)"
        pinned = ipfs.is_pinned(row["ipns_name"], pinned_cids)
        entries.append(
            BrowseEntry(
                source=row["node_id"],
                name=name,
                ipns_name=row["ipns_name"],
                pinned=pinned,
            )
        )

    return entries
