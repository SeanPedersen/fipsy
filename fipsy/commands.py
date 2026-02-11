"""Click subcommands for fipsy CLI."""

import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import click

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
        click.echo(f"Peer Index: ipns://{peer_id}")
        db.upsert_discovered(peer_id, peer_id)  # index: key=node_id, name=NULL
        for name, (key_id, resolved) in ipns_keys.items():
            if resolved:
                cid = resolved.split("/")[-1]
                click.echo(f"  {name} (IPNS): ipns://{key_id}")
                click.echo(f"  {name} (IPFS): ipfs://{cid}")
                if pin:
                    if _pin_cid(cid):
                        click.echo(f"  {name}: pinned")
                    else:
                        click.echo(f"  {name}: pin failed")
                db.upsert_discovered(peer_id, key_id, name=name)
            else:
                click.echo(f"  {name}: unresolved... (ipns://{key_id})")
                db.upsert_discovered(peer_id, key_id, name=name)
        click.echo()


def _resolve_key(key_id: str) -> str | None:
    """Resolve an IPNS key to its CID. Returns None on failure."""
    try:
        return ipfs.name_resolve(key_id)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _fetch_peer_index(
    peer_id: str,
) -> tuple[str, dict[str, tuple[str, str | None]]] | None:
    """Fetch a single peer's index.json and resolve IPNS keys.

    Returns (peer_id, {name: (key_id, resolved_path_or_none)}) or None.
    """
    try:
        raw = ipfs.cat_path(f"/ipns/{peer_id}/index.json")
        data = json.loads(raw)
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ):
        return None

    ipns_keys: dict[str, str] = data.get("ipns", {})
    if not ipns_keys:
        return None

    # Resolve all IPNS keys concurrently
    resolved: dict[str, tuple[str, str | None]] = {}
    with ThreadPoolExecutor(max_workers=len(ipns_keys)) as pool:
        futures = {
            pool.submit(_resolve_key, key_id): name
            for name, key_id in ipns_keys.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            resolved[name] = (ipns_keys[name], future.result())

    return (peer_id, resolved)


def _fetch_peer_indexes(
    peers: list[str],
) -> list[tuple[str, dict[str, tuple[str, str | None]]]]:
    """Fetch indexes from all peers concurrently."""
    results: list[tuple[str, dict[str, tuple[str, str | None]]]] = []
    with ThreadPoolExecutor(max_workers=len(peers)) as pool:
        futures = {pool.submit(_fetch_peer_index, pid): pid for pid in peers}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    return results


def _publish_key(name: str, dir_path: str) -> str | None:
    """Add directory and publish under IPNS key. Returns CID on success."""
    try:
        cid = ipfs.add_directory(dir_path)
        ipfs.name_publish(cid, key=name, ttl="1m")
        return cid
    except subprocess.CalledProcessError:
        return None


def _publish_keys(keys: dict[str, str]) -> None:
    """Publish all IPNS keys by adding their directories from cwd."""
    cwd = os.getcwd()
    for name, key_id in keys.items():
        dir_path = os.path.join(cwd, name)
        if not os.path.isdir(dir_path):
            click.echo(f"  {name}: skipped (directory not found)")
            continue
        cid = _publish_key(name, dir_path)
        if cid:
            click.echo(f"  {name}: ipns://{key_id}")
            click.echo(f"  {name}: ipfs://{cid}")
        else:
            click.echo(f"  {name}: failed")


@click.command()
def index() -> None:
    """List local and discovered IPNS keys."""
    ensure_ipfs()
    db.init_db()

    # Local keys
    keys = ipfs.key_list()
    if keys:
        click.echo("Local keys:")
        for name, key_id in keys.items():
            click.echo(f"  {name}: ipns://{key_id}")
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
                name = row["name"] or "(index)"
                click.echo(f"    {name}: ipns://{row['ipns_key']}{pin_marker}")


@click.command()
@click.argument("dir_path", type=click.Path(exists=True, file_okay=False))
def add(dir_path: str) -> None:
    """Add a directory to IPFS and publish it under an IPNS key."""
    ensure_ipfs()

    key_name = os.path.basename(os.path.normpath(dir_path))
    if not key_name:
        raise click.ClickException("Could not infer key name from directory path")

    keys = ipfs.key_list()
    if key_name not in keys:
        click.echo(f"Creating IPNS key: {key_name}")
        ipfs.key_gen(key_name)

    click.echo(f"Adding {dir_path} to IPFS...")
    cid = ipfs.add_directory(dir_path)
    click.echo(f"CID: {cid}")
    click.echo(f"ipfs://{cid}")

    click.echo(f"Publishing under IPNS key: {key_name}...")
    ipfs.name_publish(cid, key=key_name, ttl="1m")

    keys = ipfs.key_list()
    ipns_hash = keys.get(key_name, "")
    click.echo(f"ipns://{ipns_hash}")


@click.command()
def publish() -> None:
    """Publish a discovery index of all your IPNS keys."""
    ensure_ipfs()

    keys = ipfs.key_list()
    published_keys = {name: kid for name, kid in keys.items() if name != "self"}

    if not published_keys:
        click.echo("No IPNS keys found (besides self). Use `fipsy add` first.")
        return

    # Publish all IPNS keys by adding directories from cwd
    click.echo(f"Publishing {len(published_keys)} IPNS key(s)...")
    _publish_keys(published_keys)

    discovery_dir = tempfile.mkdtemp(prefix="fipsy-index-")
    try:
        _write_index_json(discovery_dir, published_keys)
        _write_index_html(discovery_dir, published_keys)

        click.echo("Publishing discovery index under IPNS self...")
        cid = ipfs.add_directory(discovery_dir)
        ipfs.name_publish(cid, ttl="1m")
        click.echo(f"  ipns://{ipfs.node_id()}")
        click.echo(f"  ipfs://{cid}")
    finally:
        shutil.rmtree(discovery_dir, ignore_errors=True)


def _write_index_json(directory: str, keys: dict[str, str]) -> None:
    data = {"ipns": keys}
    path = os.path.join(directory, "index.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _write_index_html(directory: str, keys: dict[str, str]) -> None:
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
    for name, key_id in keys.items():
        lines.append(
            f'    <li><a href="ipns://{key_id}">{name}</a> <code>{key_id}</code></li>'
        )
    lines.extend(
        [
            "  </ul>",
            "</body>",
            "</html>",
        ]
    )
    path = os.path.join(directory, "index.html")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


