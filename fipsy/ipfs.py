"""Pure wrappers around the `ipfs` CLI binary."""

import shutil
import subprocess
import time

DAEMON_STARTUP_TIMEOUT = 15
DAEMON_POLL_INTERVAL = 1


def run_ipfs(*args: str, timeout: float | None = None) -> str:
    result = subprocess.run(
        ["ipfs", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def is_installed() -> bool:
    return shutil.which("ipfs") is not None


def is_daemon_running() -> bool:
    try:
        run_ipfs("id")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def start_daemon() -> None:
    subprocess.Popen(
        ["ipfs", "daemon", "--init"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    elapsed = 0
    while elapsed < DAEMON_STARTUP_TIMEOUT:
        time.sleep(DAEMON_POLL_INTERVAL)
        elapsed += DAEMON_POLL_INTERVAL
        if is_daemon_running():
            return
    raise RuntimeError("IPFS daemon failed to start within timeout")


def node_id() -> str:
    return run_ipfs("id", "-f=<id>")


def swarm_peers() -> list[str]:
    output = run_ipfs("swarm", "peers")
    if not output:
        return []
    # Each line is a multiaddr like /ip4/.../p2p/<peer_id>
    return list({line.rstrip("/").split("/")[-1] for line in output.splitlines()})


DEFAULT_CAT_TIMEOUT = 5


def cat_path(path: str, timeout: float = DEFAULT_CAT_TIMEOUT) -> str:
    return run_ipfs("cat", path, timeout=timeout)


def key_list() -> dict[str, str]:
    """Return {name: key_id} for all IPNS keys."""
    output = run_ipfs("key", "list", "-l")
    keys: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key_id, name = parts[0], parts[1]
            keys[name] = key_id
    return keys


def key_gen(name: str) -> str:
    return run_ipfs("key", "gen", name)


def add_directory(dir_path: str) -> str:
    """Add directory recursively, return root CID v1."""
    return run_ipfs("add", "-r", "-Q", "--cid-version=1", "--raw-leaves", dir_path)


DEFAULT_RESOLVE_TIMEOUT = 10


def name_resolve(key_id: str, timeout: float = DEFAULT_RESOLVE_TIMEOUT) -> str:
    """Resolve an IPNS key to its current IPFS path."""
    return run_ipfs(
        "name", "resolve", "--recursive", f"/ipns/{key_id}", timeout=timeout
    )


def name_publish(
    cid: str,
    key: str | None = None,
    lifetime: str | None = None,
    ttl: str | None = None,
) -> str:
    args = ["name", "publish"]
    if key:
        args.append(f"--key={key}")
    if lifetime:
        args.append(f"--lifetime={lifetime}")
    if ttl:
        args.append(f"--ttl={ttl}")
    args.append(f"/ipfs/{cid}")
    return run_ipfs(*args)


def pin_add(cid: str, recursive: bool = True) -> str:
    """Pin a CID to local storage."""
    args = ["pin", "add"]
    if recursive:
        args.append("--recursive=true")
    else:
        args.append("--recursive=false")
    args.append(cid)
    return run_ipfs(*args)


def pin_ls() -> set[str]:
    """List all pinned CIDs."""
    output = run_ipfs("pin", "ls", "--type=recursive", "-q")
    if not output:
        return set()
    return set(output.splitlines())


def is_pinned(ipns_key: str, pinned_cids: set[str] | None = None) -> bool:
    """Check if an IPNS key's resolved content is pinned."""
    if pinned_cids is None:
        pinned_cids = pin_ls()
    try:
        resolved = name_resolve(ipns_key, timeout=5)
        cid = resolved.split("/")[-1]
        return cid in pinned_cids
    except Exception:
        return False
