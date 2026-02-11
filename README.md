# Fipsy - IPFS discovery

A useful Python CLI for using IPFS to share and discover content.

Start your daemon with pubsub IPNS sync enabled (for faster sync): $ ipfs daemon --enable-namesys-pubsub

## fipsy scan

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

## fipsy add $DIR_PATH

Infers IPNS_KEY from $DIR_PATH (uses name of last dir)

## fipsy publish

This creates an index of all your local IPNS keys and makes it publicly discoverable for peers in the network.

## fipsy index

Show your local IPNS keys and discovered keys from peers.
