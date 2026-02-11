# Fipsy - IPFS discovery

CLI tool using IPFS to share and discover content decentralized.

Start your daemon with pubsub IPNS sync enabled (for faster sync):
```bash
ipfs daemon --enable-namesys-pubsub
```

## Commands

### fipsy publish

This creates an index of all your local IPNS keys and makes it publicly discoverable for peers in the network.

Fipsy defines the content of your public IPNS self-name as a dir of index.html and index.json - containing a list of your IPNS keys + names. This allows all participants in the network to discover and browse their data via IPNS keys.

### fipsy add $DIR_PATH

Infers IPNS_KEY from $DIR_PATH (uses name of last dir) and publishes dir.

### fipsy scan

Discover Self Index of Peers
This works in a local network - allowing true decentralized networking.

Show connected nodes (returns list of $NODE_ID): ipfs swarm peers
Discover public self IPNS content of node: ipfs ls /ipns/$NODE_ID
Show index: ipfs cat /ipns/$NODE_ID/index.json

Use `--pin` to pin all discovered content:

```bash
fipsy scan --pin
```

Discovered keys are saved to `~/.config/fipsy/discovered.db` and shown by `fipsy index`.

### fipsy index

Show your local IPNS keys and discovered keys from peers.

## References

- <ipns://k2k4r8nrj3ghk8ymc70o9vvkzusiyncbmflw85ctv3j1ktrhddwh7nvu/posts/ipfs/>
- <https://seanpedersen.github.io/posts/ipfs/>