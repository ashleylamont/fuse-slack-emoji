# Slack Emoji FS viewer

A small, read-only web viewer for the immutable trees and root history stored by
Slack Emoji FS. It is a separate package from the filesystem and does not mount
or modify the object store.

## Run it

From this directory, install the package and its editable dependency on the
parent project:

```console
uv sync
```

To inspect a Slack-backed namespace, put the token in the repository `.env`:

```console
SLACK_USER_TOKEN=xoxp-...
```

Then run:

```console
uv run slack-emoji-fs-viewer --namespace maintest
```

Then open <http://127.0.0.1:8765>. The server binds only to localhost by
default. The token environment variable can be changed with
`--slack-token-env`.

An existing directory created by `LocalFileObjectStore` can be inspected
without Slack access:

```console
uv run slack-emoji-fs-viewer \
  --store local \
  --directory ../objects \
  --namespace maintest
```

Use `--host` and `--port` to change the listen address. Binding to a public
interface exposes filesystem metadata and should only be done on a trusted
network.

## What it shows

- all root snapshots in timestamp order;
- the parent chain for a selected root;
- an expandable directory/file tree with a node metadata inspector;
- a visual parent timeline for snapshot history;
- added, modified, and removed paths relative to each snapshot's parent;
- lineage playback that animates snapshot changes from oldest to newest, with a
  scrubber for moving directly between frames;
- inode, dirent, and data-chunk object IDs.

File payloads are deliberately not loaded or served. Both supported backends
are used through read operations only; the local backend explicitly rejects
writes.

## Test it

```console
uv run pytest
```

The tests use `MemoryObjectStore` and exercise HTTP routing directly without
opening a socket. They require no Slack token or internet access.
