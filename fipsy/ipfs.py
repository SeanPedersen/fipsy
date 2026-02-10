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
    return run_ipfs("key", "gen", name, "--type=rsa", "--size=2048")


def add_directory(dir_path: str) -> str:
    """Add directory recursively, return root CID."""
    return run_ipfs("add", "-r", "-Q", dir_path)


def name_publish(
    cid: str,
    key: str | None = None,
    lifetime: str | None = None,
) -> str:
    args = ["name", "publish"]
    if key:
        args.append(f"--key={key}")
    if lifetime:
        args.append(f"--lifetime={lifetime}")
    args.append(f"/ipfs/{cid}")
    return run_ipfs(*args)
