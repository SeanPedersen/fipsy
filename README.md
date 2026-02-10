# Fipsy - IPFS discovery

A useful Python CLI for using IPFS to share and discover content.

## fipsy scan

Discover Self Index of Peers
This works in a local network - allowing true decentralized networking.

Show connected nodes (returns list of $NODE_ID): ipfs swarm peers
Discover public self IPNS content of node: ipfs ls /ipns/$NODE_ID
Show index: ipfs cat /ipns/$NODE_ID/index.json

## fipsy add $DIR_PATH

Infer IPNS_KEY from $DIR_PATH (use name of last dir)

```bash
#!/usr/bin/env sh
set -e

OUT_DIR=$DIR_PATH
IPNS_KEY="your-website-id"

# 1. Detect IPFS
if ! command -v ipfs >/dev/null 2>&1; then
  echo "❌ ipfs not installed"
  exit 1
fi

# 2. Ensure daemon is running
if ! ipfs id >/dev/null 2>&1; then
  echo "🚀 Starting IPFS daemon..."
  ipfs daemon --init &
  sleep 5
fi

# 3. Check out/ exists
if [ ! -d "$OUT_DIR" ]; then
  echo "❌ $OUT_DIR directory not found"
  exit 1
fi

# 4. Create IPNS key if missing
if ! ipfs key list | grep -q "$IPNS_KEY"; then
  echo "🔑 Creating IPNS key: $IPNS_KEY"
  ipfs key gen "$IPNS_KEY" --type=rsa --size=2048
fi

# 5. Add site to IPFS
echo "📦 Adding $OUT_DIR to IPFS..."
CID=$(ipfs add -r -Q "$OUT_DIR")
echo "✅ CID: $CID"
echo "🌐 Direct IPFS link (works offline):"
echo "https://ipfs.io/ipfs/$CID"

# 6. Publish to IPNS
echo "🔗 Publishing $CID via IPNS key: $IPNS_KEY..."
ipfs name publish --key="$IPNS_KEY" /ipfs/"$CID"

# 7. Get IPNS hash
IPNS_HASH=$(ipfs key list -l | grep "$IPNS_KEY" | awk '{print $1}')
echo "🌐 Access your blog via IPNS (stable link - works offline):"
echo "https://ipfs.io/ipns/$IPNS_HASH"
```

## fipsy publish

This creates an index of all your local IPNS keys and makes it publicly discoverable for peers in the network.

```bash
#!/usr/bin/env sh
set -e

DISCOVERY_DIR=".ipns-index"

echo "📡 Building IPNS discovery index..."

# 1. Ensure IPFS is available
command -v ipfs >/dev/null 2>&1 || {
  echo "❌ ipfs not installed"
  exit 1
}

# 2. Ensure daemon is running
if ! ipfs id >/dev/null 2>&1; then
  echo "🚀 Starting IPFS daemon..."
  ipfs daemon >/tmp/ipfs.log 2>&1 &
  until ipfs id >/dev/null 2>&1; do
    sleep 1
  done
fi

# 3. Prepare directory
rm -rf "$DISCOVERY_DIR"
mkdir -p "$DISCOVERY_DIR"

# 4. Generate index.json
echo "🧾 Generating index.json..."

echo '{ "ipns": {' > "$DISCOVERY_DIR/index.json"

FIRST=1
ipfs key list -l | while read -r KEY_ID KEY_NAME; do
  [ "$KEY_NAME" = "self" ] && continue

  if [ $FIRST -eq 0 ]; then
    echo ',' >> "$DISCOVERY_DIR/index.json"
  fi
  FIRST=0

  printf '  "%s": "%s"' "$KEY_NAME" "$KEY_ID" >> "$DISCOVERY_DIR/index.json"
done

echo '' >> "$DISCOVERY_DIR/index.json"
echo '} }' >> "$DISCOVERY_DIR/index.json"

# 5. Generate index.html
echo "🌐 Generating index.html..."

cat > "$DISCOVERY_DIR/index.html" <<'EOF'
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>IPNS Index</title>
  <style>
    body { font-family: sans-serif; padding: 2rem; }
    li { margin: 0.5rem 0; }
    code { background: #eee; padding: 0.2rem 0.4rem; }
  </style>
</head>
<body>
  <h1>IPNS Index</h1>
  <ul>
EOF

ipfs key list -l | while read -r KEY_ID KEY_NAME; do
  [ "$KEY_NAME" = "self" ] && continue
  echo "    <li><a href=\"http://ipfs.io/ipns/$KEY_ID\">$KEY_NAME</a> <code>$KEY_ID</code></li>" >> "$DISCOVERY_DIR/index.html"
done

cat >> "$DISCOVERY_DIR/index.html" <<'EOF'
  </ul>
</body>
</html>
EOF

# 6. Add to IPFS
echo "📦 Adding discovery index to IPFS..."
CID=$(ipfs add -r -Q "$DISCOVERY_DIR")
echo "✅ CID: $CID"

# 7. Publish under self
echo "🔗 Publishing discovery index under self..."
ipfs name publish --lifetime=1m /ipfs/"$CID"

echo "🎉 Done!"
echo
echo "🔍 Discoverable via:"
echo "  ipfs ls /ipns/$(ipfs id -f='<id>')"
echo "  ipfs cat /ipns/$(ipfs id -f='<id>')/index.json"
echo "  http://ipfs.io/ipns/$(ipfs id -f='<id>')"
```
