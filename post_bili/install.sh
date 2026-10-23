#!/bin/bash
# 装 B 站投稿工具 biliup（GitHub biliup/biliup 的命令行版，单个可执行文件）到 bin/biliup。
# 固定版本 + 校验 sha256；升级时改 VERSION 和 SHA256，先在一首歌上用 --only-self 试过再换。
set -euo pipefail

VERSION=v1.2.11
SHA256=078335f23ab27df185a9757ffc30dfd7299648679de32aaa576efd5257326e62   # aarch64-macos 里的 biliup
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

NAME="biliupR-$VERSION-aarch64-macos"
curl -fsSL -o "$TMP/$NAME.tar.xz" "https://github.com/biliup/biliup/releases/download/$VERSION/$NAME.tar.xz"
tar -xf "$TMP/$NAME.tar.xz" -C "$TMP"
echo "$SHA256  $TMP/$NAME/biliup" | shasum -a 256 -c -
install -m 755 "$TMP/$NAME/biliup" "$ROOT/bin/biliup"
xattr -c "$ROOT/bin/biliup" 2>/dev/null || true
"$ROOT/bin/biliup" --version
