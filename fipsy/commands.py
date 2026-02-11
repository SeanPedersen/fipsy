"""Click subcommands for fipsy CLI."""

import json
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from tqdm import tqdm

from fipsy import db, ipfs

DISCOVERY_DIR_NAME = ".ipns-index"


def ensure_ipfs() -> None:
    if not ipfs.is_installed():
        raise click.ClickException("ipfs is not installed")
    if not ipfs.is_daemon_running():
        click.echo("Starting IPFS daemon...")
        ipfs.start_daemon()
        click.echo("IPFS daemon started.")


def _pin_cid(cid: str) -> bool:
    """Pin a CID recursively. Returns True on success."""
    try:
        ipfs.pin_add(cid)
        return True
    except subprocess.CalledProcessError:
        return False


@click.command()
@click.option("--pin", is_flag=True, help="Pin discovered content.")
def scan(pin: bool) -> None:
    """Discover content published by local IPFS peers.

    Tip: Enable IPNS-over-PubSub on both nodes for near-instant discovery:

        ipfs daemon --enable-namesys-pubsub
    """
    ensure_ipfs()
    db.init_db()

    peers = ipfs.swarm_peers()
    if not peers:
        click.echo("No peers found.")
        return

    click.echo(f"Found {len(peers)} peer(s). Scanning for published indexes...\n")

    results = _fetch_peer_indexes(peers)
    if not results:
        click.echo("No published indexes found.")
        return

    for peer_id, ipns_keys in results:
        click.echo(f"Peer Index: ipfs.io/ipns/{peer_id}")
        db.upsert_discovered(peer_id, peer_id)  # index: key=node_id, name=NULL
        for name, (ipns_name, resolved) in ipns_keys.items():
            if resolved:
                cid = resolved.split("/")[-1]
                click.echo(f"  {name} (IPNS): ipfs.io/ipns/{ipns_name}")
                click.echo(f"  {name} (IPFS): ipfs.io/ipfs/{cid}")
                if pin:
                    if _pin_cid(cid):
                        click.echo(f"  {name}: pinned")
                    else:
                        click.echo(f"  {name}: pin failed")
                db.upsert_discovered(peer_id, ipns_name, name=name)
            else:
                click.echo(f"  {name}: unresolved... (ipfs.io/ipns/{ipns_name})")
                db.upsert_discovered(peer_id, ipns_name, name=name)
        click.echo()


def _resolve_key(ipns_name: str) -> str | None:
    """Resolve an IPNS name to its CID. Returns None on failure."""
    try:
        return ipfs.name_resolve(ipns_name)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _fetch_peer_index(
    peer_id: str,
    cat_timeout: float = ipfs.DEFAULT_CAT_TIMEOUT,
) -> tuple[str, dict[str, tuple[str, str | None]]] | None:
    """Fetch a single peer's index.json and resolve IPNS keys.

    Returns (peer_id, {name: (key_id, resolved_path_or_none)}) or None.
    """
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

    # Resolve all IPNS keys concurrently
    MAX_WORKERS = 10
    resolved: dict[str, tuple[str, str | None]] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(ipns_keys))) as pool:
        futures = {
            pool.submit(_resolve_key, key_id): name
            for name, key_id in ipns_keys.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            resolved[name] = (ipns_keys[name], future.result())

    return (peer_id, resolved)


MANY_PEERS_THRESHOLD = 20
FAST_CAT_TIMEOUT = 2.69


def _fetch_peer_indexes(
    peers: list[str],
) -> list[tuple[str, dict[str, tuple[str, str | None]]]]:
    """Fetch indexes from all peers concurrently."""
    MAX_WORKERS = 20
    many_peers = len(peers) > MANY_PEERS_THRESHOLD
    cat_timeout = FAST_CAT_TIMEOUT if many_peers else ipfs.DEFAULT_CAT_TIMEOUT

    results: list[tuple[str, dict[str, tuple[str, str | None]]]] = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(peers))) as pool:
        futures = {
            pool.submit(_fetch_peer_index, pid, cat_timeout): pid for pid in peers
        }
        iterator = as_completed(futures)
        if many_peers:
            iterator = tqdm(iterator, total=len(peers), desc="Scanning peers")
        for future in iterator:
            result = future.result()
            if result:
                results.append(result)
    return results


def _publish_entry(key: str, dir_path: Path, ipns_name: str) -> str | None:
    """Add directory and publish under IPNS name. Returns CID on success."""
    if not dir_path.is_dir():
        click.echo(f"  {key}: skipped (directory not found at {dir_path})")
        return None
    try:
        cid = ipfs.add_directory(str(dir_path))
        ipfs.name_publish(cid, key=key, ttl="1m")
        click.echo(f"  {key}: ipfs.io/ipns/{ipns_name}")
        click.echo(f"  {key}: ipfs.io/ipfs/{cid}")
        return cid
    except subprocess.CalledProcessError:
        click.echo(f"  {key}: failed")
        return None


@click.command()
def index() -> None:
    """List local and discovered IPNS keys."""
    ensure_ipfs()
    db.init_db()

    # Build lookup from published table: key -> path
    published_paths = {entry["key"]: entry["path"] for entry in db.list_published()}

    # Local keys
    keys = ipfs.key_list()
    if keys:
        click.echo("Local keys:")
        for key, ipns_name in keys.items():
            display_name = "(index)" if key == "self" else key
            path_suffix = f" ({published_paths[key]})" if key in published_paths else ""
            click.echo(f"  {display_name}: ipfs.io/ipns/{ipns_name}{path_suffix}")
    else:
        click.echo("No local IPNS keys.")

    # Discovered keys
    discovered = db.list_discovered()
    if discovered:
        click.echo("\nDiscovered keys:")
        pinned_cids = ipfs.pin_ls()

        # Group by node_id
        peers: dict[str, list[dict]] = {}
        for row in discovered:
            peers.setdefault(row["node_id"], []).append(row)

        for node_id, rows in peers.items():
            click.echo(f"  Peer: {node_id}")
            for row in rows:
                pinned = ipfs.is_pinned(row["ipns_key"], pinned_cids)
                pin_marker = " [pinned]" if pinned else ""
                key = row["name"] or "(index)"
                click.echo(f"    {key}: ipfs.io/ipns/{row['ipns_key']}{pin_marker}")


@click.command()
@click.argument(
    "dir_path", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
def add(dir_path: Path) -> None:
    """Add a directory to IPFS and publish it under an IPNS key."""
    ensure_ipfs()
    db.init_db()

    abs_path = dir_path.resolve()
    default_name = abs_path.name
    if not default_name:
        raise click.ClickException("Could not infer key name from directory path")

    key_name = click.prompt("Name", default=default_name)

    keys = ipfs.key_list()
    if key_name not in keys:
        click.echo(f"Creating IPNS key: {key_name}")
        ipfs.key_gen(key_name)

    click.echo(f"Adding {dir_path} to IPFS...")
    cid = ipfs.add_directory(str(abs_path))
    click.echo(f"ipfs.io/ipfs/{cid}")

    click.echo(f"Publishing under IPNS key: {key_name}...")
    ipfs.name_publish(cid, key=key_name, ttl="1m")

    keys = ipfs.key_list()
    ipns_name = keys.get(key_name, "")
    click.echo(f"ipfs.io/ipns/{ipns_name}")

    db.upsert_published(str(abs_path), key_name)


@click.command()
def publish() -> None:
    """Publish a discovery index of all your IPNS keys."""
    ensure_ipfs()
    db.init_db()

    published = db.list_published()
    if not published:
        click.echo("No published directories. Use `fipsy add` first.")
        return

    keys = ipfs.key_list()
    click.echo(f"Publishing {len(published)} directory(s)...")

    # Track successfully published keys for the index
    published_keys: dict[str, str] = {}
    for entry in published:
        key = entry["key"]
        path = Path(entry["path"])
        ipns_name = keys.get(key)
        if not ipns_name:
            click.echo(f"  {key}: skipped (IPNS name not found)")
            continue
        cid = _publish_entry(key, path, ipns_name)
        if cid:
            published_keys[key] = ipns_name

    if not published_keys:
        click.echo("No directories were published successfully.")
        return

    discovery_dir = Path(tempfile.mkdtemp(prefix="fipsy-index-"))
    try:
        _write_index_json(discovery_dir, published_keys)
        _write_index_html(discovery_dir, published_keys)

        click.echo("Publishing discovery index under IPNS self...")
        cid = ipfs.add_directory(str(discovery_dir))
        ipfs.name_publish(cid, ttl="1m")
        click.echo(f"  ipfs.io/ipns/{ipfs.node_id()}")
        click.echo(f"  ipfs.io/ipfs/{cid}")
    finally:
        shutil.rmtree(discovery_dir, ignore_errors=True)


def _write_index_json(directory: Path, keys: dict[str, str]) -> None:
    data = {"ipns": keys}
    (directory / "index.json").write_text(json.dumps(data, indent=2))


def _write_index_html(directory: Path, keys: dict[str, str]) -> None:
    lines = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '  <meta charset="utf-8">',
        "  <title>IPNS Index</title>",
        "  <style>",
        "    body { font-family: sans-serif; padding: 2rem; }",
        "    li { margin: 0.5rem 0; }",
        "    code { background: #eee; padding: 0.2rem 0.4rem; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>IPNS Index</h1>",
        "  <ul>",
    ]
    for key_name, ipns_name in keys.items():
        lines.append(
            f'    <li><a href="ipfs.io/ipns/{ipns_name}">{key_name}</a> <code>{ipns_name}</code></li>'
        )
    lines.extend(
        [
            "  </ul>",
            "</body>",
            "</html>",
        ]
    )
    (directory / "index.html").write_text("\n".join(lines) + "\n")
