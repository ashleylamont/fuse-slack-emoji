# SlackEmojiFS

A FUSE filesystem backed by Slack custom emoji. Files become PNG-encoded emoji
objects; emoji names become object IDs. This is intentionally a terrible way
to store files and a surprisingly nice way to learn how a filesystem works.

It was built for a talk, mostly because “what if Slack emoji were a storage
backend?” is a much more interesting way to learn about filesystems than
another diagram of an inode.

## How it works

- Files are split into chunks and encoded into lossless PNGs.
- Those PNGs are uploaded as custom Slack emoji.
- Roots, inodes, directory entries, and chunks are all objects with emoji names
  as their IDs.
- Slack does not let us edit an emoji image in place, so writes become
  copy-on-write updates and old roots become snapshots.

None of this makes Slack a good place to store files. It does make the moving
parts of a filesystem very hard to ignore.

## Run it

```bash
uv sync
```

Put a Slack **user token** (`xoxp-…`, not a bot token) in `.env`:

```bash
SLACK_USER_TOKEN=xoxp-...
```

The token needs these user scopes:

- `admin.teams:write` to add the custom emoji that hold the objects;
- `emoji:read` to find those objects again; and
- `files:write` to stage the PNG, make its URL public for Slack, then delete
  the staging file.

The emoji-creation API is an Enterprise Slack API: install the app at the
organisation level with an Org Admin or Owner account. This is deliberately a
weird filesystem, and it has correspondingly weird setup requirements.

Then mount it somewhere:

```bash
uv run python main.py --namespace myexperiment /path/to/mount
```

Pick a namespace so you do not accidentally mix this experiment with someone
else’s. `--buffer-writes` delays publishing file contents until flush and
currently needs FUSE’s `-s` flag.

## Have a poke around

`viewer/` is a separate, read-only web viewer for the object trees and their
history. It is useful for seeing the snapshots that the filesystem leaves
behind without mounting or changing anything.

```bash
cd viewer
uv sync
uv run slack-emoji-fs-viewer --namespace myexperiment
```

## Test it

```bash
uv run pytest
```

Most tests use in-memory stores, so they do not need a Slack token or network
access.
