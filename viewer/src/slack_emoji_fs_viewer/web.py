"""Small, dependency-free HTTP UI for :class:`HistoryViewer`."""

from __future__ import annotations

import dataclasses
import json
import logging
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from .history import HistoryViewer


logger = logging.getLogger(__name__)


def _list_roots(viewer: HistoryViewer) -> Any:
    method = getattr(viewer, "list_roots", None)
    return method() if method is not None else viewer.list_snapshots()


def _get_tree(viewer: HistoryViewer, root_id: str) -> Any:
    method = getattr(viewer, "get_tree", None)
    return method(root_id) if method is not None else viewer.materialize_tree(root_id)


def _get_history(viewer: HistoryViewer, root_id: str | None) -> Any:
    method = getattr(viewer, "get_history", None)
    return method(root_id) if method is not None else viewer.root_history(root_id)


def _get_diff(viewer: HistoryViewer, root_id: str) -> Any:
    return viewer.diff_from_parent(root_id)


def _json_value(value: Any) -> Any:
    """Convert common model values into a JSON-safe representation."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_value(dataclasses.asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_value(model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return {"byte_length": len(value), "preview_hex": value[:32].hex()}
    if isinstance(value, Enum):
        return _json_value(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


_INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Slack Emoji FS history</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      --panel: color-mix(in srgb, Canvas 94%, CanvasText 6%);
      --line: color-mix(in srgb, CanvasText 18%, transparent);
      --muted: color-mix(in srgb, CanvasText 62%, transparent);
      --accent: #7289ff;
      --selected: color-mix(in srgb, var(--accent) 18%, transparent);
      --added: #28a66a;
      --modified: #d59020;
      --removed: #d95656;
    }
    * { box-sizing: border-box; }
    body { max-width: 1440px; margin: 0 auto; padding: 1.25rem; background: Canvas; color: CanvasText; }
    header { display: flex; gap: .75rem; align-items: baseline; flex-wrap: wrap; }
    h1 { font-size: 1.45rem; margin: 0; }
    h2 { font-size: .92rem; margin: 0 0 .75rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
    .muted { color: var(--muted); }
    main { display: grid; grid-template-columns: minmax(17rem, 24rem) minmax(30rem, 1fr); gap: 1rem; margin-top: 1rem; }
    section { border: 1px solid var(--line); border-radius: .75rem; background: var(--panel); min-width: 0; }
    .snapshot-panel { padding: 1rem; max-height: calc(100vh - 6rem); overflow: auto; }
    .workspace { padding: 1rem; }
    button { font: inherit; color: inherit; cursor: pointer; }
    #roots button { display: block; width: 100%; text-align: left; border: 1px solid transparent; border-radius: .45rem; background: transparent; padding: .6rem; margin: .2rem 0; }
    #roots button:hover { background: color-mix(in srgb, CanvasText 7%, transparent); }
    #roots button[aria-current=true] { border-color: var(--accent); background: var(--selected); }
    .snapshot-id { display: block; font: 600 .82rem ui-monospace, SFMono-Regular, Menlo, monospace; }
    .snapshot-time { display: block; margin-top: .25rem; font-size: .75rem; color: var(--muted); }
    .tabs { display: flex; gap: .35rem; margin-bottom: .8rem; border-bottom: 1px solid var(--line); padding-bottom: .7rem; }
    .tabs button { border: 1px solid var(--line); border-radius: .4rem; background: transparent; padding: .42rem .7rem; }
    .tabs button.active { border-color: var(--accent); background: var(--selected); }
    .tabs button:disabled { opacity: .45; cursor: default; }
    .tabs .play { margin-left: auto; }
    #detail { min-height: 28rem; }
    .loading, .empty { padding: 2rem; text-align: center; color: var(--muted); }
    .error { padding: 1rem; color: #e45757; white-space: pre-wrap; }
    .tree-layout { display: grid; grid-template-columns: minmax(20rem, 1.35fr) minmax(16rem, .65fr); gap: 1rem; }
    .tree-browser, .inspector { border: 1px solid var(--line); border-radius: .55rem; background: Canvas; min-width: 0; }
    .tree-browser { padding: .6rem; overflow: auto; max-height: calc(100vh - 12rem); }
    .inspector { padding: .9rem; align-self: start; position: sticky; top: 1rem; overflow-wrap: anywhere; }
    .tree, .tree ul { list-style: none; margin: 0; padding-left: 1rem; }
    .tree { padding-left: 0; }
    .tree details > summary, .file-row { border: 0; border-radius: .35rem; background: transparent; width: 100%; padding: .34rem .4rem; text-align: left; }
    .tree details > summary:hover, .file-row:hover, .node-selected { background: var(--selected); }
    .change-added { box-shadow: inset 3px 0 var(--added); background: color-mix(in srgb, var(--added) 14%, transparent) !important; animation: change-pulse .8s ease-out; }
    .change-modified { box-shadow: inset 3px 0 var(--modified); background: color-mix(in srgb, var(--modified) 14%, transparent) !important; animation: change-pulse .8s ease-out; }
    @keyframes change-pulse { from { filter: brightness(1.55); } to { filter: none; } }
    .tree details > summary { cursor: pointer; }
    .tree details > summary::marker { color: var(--muted); }
    .node-icon { display: inline-block; width: 1.45rem; text-align: center; }
    .node-name { font: .86rem ui-monospace, SFMono-Regular, Menlo, monospace; }
    .child-count { margin-left: .45rem; color: var(--muted); font-size: .72rem; }
    .inspector h3 { margin: 0 0 .7rem; font-size: 1rem; }
    .metadata { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: .42rem .75rem; margin: 0; font-size: .8rem; }
    .metadata dt { color: var(--muted); }
    .metadata dd { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .raw { margin-top: .9rem; font-size: .78rem; }
    pre { overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: .75rem ui-monospace, SFMono-Regular, Menlo, monospace; }
    .history { position: relative; list-style: none; padding: .4rem 0 .4rem 1.35rem; margin: 0; }
    .history::before { content: ''; position: absolute; left: .42rem; top: .9rem; bottom: .9rem; border-left: 2px solid var(--line); }
    .history li { position: relative; border: 1px solid var(--line); border-radius: .5rem; background: Canvas; padding: .75rem; margin: 0 0 .7rem; }
    .history li::before { content: ''; position: absolute; left: -1.29rem; top: 1rem; width: .65rem; height: .65rem; border-radius: 50%; background: var(--accent); }
    .history-id { font: 600 .82rem ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    .history-meta { margin-top: .4rem; color: var(--muted); font-size: .77rem; }
    .change-summary { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; border: 1px solid var(--line); border-radius: .55rem; background: Canvas; padding: .55rem .7rem; margin-bottom: .75rem; font-size: .8rem; }
    .change-count { border-radius: 999px; padding: .2rem .55rem; }
    .change-count.added { color: var(--added); background: color-mix(in srgb, var(--added) 14%, transparent); }
    .change-count.modified { color: var(--modified); background: color-mix(in srgb, var(--modified) 14%, transparent); }
    .change-count.removed { color: var(--removed); background: color-mix(in srgb, var(--removed) 14%, transparent); }
    .removed-list { flex-basis: 100%; margin: .25rem 0 0; color: var(--removed); font: .75rem ui-monospace, SFMono-Regular, Menlo, monospace; }
    .playback-label { margin-left: auto; color: var(--muted); font: .75rem ui-monospace, SFMono-Regular, Menlo, monospace; }
    .playback-scrubber { flex-basis: 100%; width: 100%; accent-color: var(--accent); cursor: ew-resize; }
    @media (max-width: 900px) { main, .tree-layout { grid-template-columns: 1fr; } .snapshot-panel { max-height: none; } .inspector { position: static; } }
  </style>
</head>
<body>
  <header><h1>Slack Emoji FS</h1><span class="muted">tree &amp; history viewer</span></header>
  <main>
    <section class="snapshot-panel"><h2>Roots / snapshots</h2><div id="roots" class="muted">Loading…</div></section>
    <section class="workspace">
      <div class="tabs">
        <button id="tree-tab" disabled>Tree</button>
        <button id="history-tab" disabled>History</button>
        <button id="all-history">All history</button>
        <button id="play-history" class="play" disabled>▶ Play lineage</button>
      </div>
      <div id="detail" class="empty">Choose a root to inspect it.</div>
    </section>
  </main>
<script>
  const rootsEl = document.querySelector('#roots');
  const detailEl = document.querySelector('#detail');
  const treeTab = document.querySelector('#tree-tab');
  const historyTab = document.querySelector('#history-tab');
  const allHistoryTab = document.querySelector('#all-history');
  const playHistoryTab = document.querySelector('#play-history');
  let selected = null;
  let selectedNodeRow = null;
  let playbackToken = 0;
  let playing = false;
  let playbackFrames = [];
  let playbackFrameIndex = 0;
  let frameRequestToken = 0;
  const diffCache = new Map();

  const pretty = value => JSON.stringify(value, null, 2);
  const rootId = value => typeof value === 'string' ? value
    : value.root_id ?? value.root_object_id ?? value.id ?? pretty(value);
  const shortId = id => id.length > 34 ? id.slice(0, 17) + '…' + id.slice(-10) : id;
  const date = seconds => seconds == null ? 'Unknown time' : new Date(seconds * 1000).toLocaleString();
  const fileSize = bytes => {
    if (bytes == null) return null;
    if (bytes < 1024) return `${bytes} bytes`;
    const units = ['KiB', 'MiB', 'GiB', 'TiB'];
    let value = bytes / 1024; let unit = units[0];
    for (let index = 1; value >= 1024 && index < units.length; index += 1) {
      value /= 1024; unit = units[index];
    }
    return `${value.toFixed(value < 10 ? 1 : 0)} ${unit} (${bytes.toLocaleString()} bytes)`;
  };
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };

  function setActiveTab(active) {
    [treeTab, historyTab, allHistoryTab, playHistoryTab].forEach(tab => tab.classList.toggle('active', tab === active));
  }

  function stopPlayback() {
    playbackToken += 1; playing = false; playHistoryTab.textContent = '▶ Play lineage';
  }

  function markSelectedRoot(id) {
    selected = id;
    document.querySelectorAll('#roots button').forEach(button => {
      button.setAttribute('aria-current', String(button.dataset.rootId === id));
    });
  }

  function showInspector(node, row, change = null) {
    if (selectedNodeRow) selectedNodeRow.classList.remove('node-selected');
    selectedNodeRow = row; row.classList.add('node-selected');
    const inspector = document.querySelector('.inspector');
    inspector.replaceChildren(element('h3', '', (node.kind === 'directory' ? '📁 ' : '📄 ') + (node.path || node.name)));
    const fields = [
      ['Change', change], ['Kind', node.kind], ['Path', node.path], ['Mode', node.mode == null ? null : '0' + node.mode.toString(8)],
      ['UID', node.uid], ['GID', node.gid], ['File size', node.kind === 'file' ? fileSize(node.size) : null], ['Inode object', node.inode_object_id],
      ['Dirent object', node.dirent_object_id], ['Chunks', node.chunk_object_ids?.length ?? 0],
      ['Modified', node.mtime == null ? null : date(node.mtime)], ['Changed', node.ctime == null ? null : date(node.ctime)],
    ];
    const list = element('dl', 'metadata');
    fields.filter(([, value]) => value != null).forEach(([label, value]) => {
      list.append(element('dt', '', label), element('dd', '', String(value)));
    });
    inspector.append(list);
    const raw = element('details', 'raw');
    raw.append(element('summary', '', 'Raw node metadata'), element('pre', '', pretty(node)));
    inspector.append(raw);
  }

  function showRemovedInspector(path) {
    const inspector = document.querySelector('.inspector');
    inspector.replaceChildren(element('h3', '', '🗑 ' + path));
    const list = element('dl', 'metadata');
    list.append(
      element('dt', '', 'Change'), element('dd', '', 'removed'),
      element('dt', '', 'Path'), element('dd', '', path),
    );
    inspector.append(list, element('p', 'muted', 'This path is absent from the current snapshot.'));
  }

  function deepestPath(paths) {
    return [...paths].sort((left, right) => {
      const depth = left.split('/').length - right.split('/').length;
      return depth || left.localeCompare(right);
    }).at(-1) || null;
  }

  function findTreeNode(node, path) {
    if (node.path === path) return node;
    for (const child of node.children || []) {
      const found = findTreeNode(child, path);
      if (found) return found;
    }
    return null;
  }

  function renderNode(node, changes, expandAll = false) {
    const item = element('li');
    const icon = element('span', 'node-icon', node.kind === 'directory' ? '📁' : '📄');
    const name = element('span', 'node-name', node.path === '/' ? '/' : node.name);
    const change = changes.added.has(node.path) ? 'added' : changes.modified.has(node.path) ? 'modified' : null;
    if (node.kind === 'directory') {
      const details = element('details'); details.open = expandAll || node.path === '/';
      const summary = element('summary', change ? `change-${change}` : ''); summary.append(icon, name);
      summary.dataset.path = node.path;
      summary.append(element('span', 'child-count', `${node.children?.length ?? 0} items`));
      summary.addEventListener('click', () => showInspector(node, summary, change));
      const children = element('ul');
      (node.children || []).forEach(child => children.append(renderNode(child, changes, expandAll)));
      details.append(summary, children); item.append(details);
    } else {
      const row = element('button', `file-row${change ? ` change-${change}` : ''}`); row.type = 'button'; row.append(icon, name);
      row.dataset.path = node.path;
      row.addEventListener('click', () => showInspector(node, row, change)); item.append(row);
    }
    return item;
  }

  function renderTree(tree, diff = null, playbackPosition = null) {
    selectedNodeRow = null;
    const changes = {
      added: new Set(diff?.added_paths || []),
      modified: new Set(diff?.modified_paths || []),
      removed: new Set(diff?.removed_paths || []),
    };
    const content = element('div');
    if (diff) {
      const summary = element('div', 'change-summary');
      summary.append(
        element('span', 'change-count added', `+ ${changes.added.size} added`),
        element('span', 'change-count modified', `~ ${changes.modified.size} modified`),
        element('span', 'change-count removed', `− ${changes.removed.size} removed`),
      );
      if (playbackPosition) {
        summary.append(element('span', 'playback-label', playbackPosition));
        const scrubber = element('input', 'playback-scrubber');
        scrubber.type = 'range'; scrubber.min = '0';
        scrubber.max = String(Math.max(0, playbackFrames.length - 1));
        scrubber.value = String(playbackFrameIndex);
        scrubber.setAttribute('aria-label', 'Snapshot timeline');
        scrubber.oninput = () => {
          stopPlayback(); setActiveTab(playHistoryTab);
          showPlaybackFrame(Number(scrubber.value));
        };
        summary.append(scrubber);
      }
      if (changes.removed.size) {
        const removed = element('div', 'removed-list', 'Removed: ' + [...changes.removed].join(', '));
        summary.append(removed);
      }
      content.append(summary);
    }
    const layout = element('div', 'tree-layout');
    const browser = element('div', 'tree-browser');
    const nodes = element('ul', 'tree'); nodes.id = 'filesystem-tree'; nodes.append(renderNode(tree, changes, playbackPosition != null));
    const inspector = element('aside', 'inspector');
    inspector.append(element('h3', '', 'Node details'), element('p', 'muted', 'Select a file or directory to inspect its object metadata.'));
    browser.append(nodes); layout.append(browser, inspector); content.append(layout); detailEl.replaceChildren(content);
    const rootSummary = browser.querySelector('summary');
    const focalPath = playbackPosition
      ? deepestPath([...changes.added, ...changes.modified])
      : null;
    if (focalPath) {
      const focalNode = findTreeNode(tree, focalPath);
      const focalRow = [...browser.querySelectorAll('[data-path]')].find(row => row.dataset.path === focalPath);
      if (focalNode && focalRow) {
        const change = changes.added.has(focalPath) ? 'added' : 'modified';
        showInspector(focalNode, focalRow, change);
        focalRow.scrollIntoView({block: 'nearest'});
      }
    } else if (playbackPosition && changes.removed.size) {
      showRemovedInspector(deepestPath(changes.removed));
    } else if (rootSummary) {
      showInspector(tree, rootSummary, changes.modified.has('/') ? 'modified' : null);
    }
  }

  function renderComparison(diff, playbackPosition = null) {
    renderTree(diff.tree, diff, playbackPosition);
  }

  function renderHistory(value) {
    const entries = Array.isArray(value) ? value : (value.roots || value.history || []);
    if (!entries.length) { detailEl.replaceChildren(element('div', 'empty', 'No history found.')); return; }
    const timeline = element('ol', 'history');
    entries.forEach(entry => {
      const id = rootId(entry); const item = element('li');
      const heading = element('div', 'history-id', id); heading.title = id; item.append(heading);
      const parent = typeof entry === 'object' ? entry.parent_root_id : null;
      const created = typeof entry === 'object' ? entry.created_at : null;
      item.append(element('div', 'history-meta', `${date(created)}${parent ? ' · parent ' + shortId(parent) : ' · initial root'}`));
      timeline.append(item);
    });
    detailEl.replaceChildren(timeline);
  }

  async function fetchJson(url) {
    const response = await fetch(url, {headers: {'Accept': 'application/json'}});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  }

  async function load(url, renderer) {
    detailEl.className = ''; detailEl.replaceChildren(element('div', 'loading', 'Loading…'));
    try {
      renderer(await fetchJson(url));
    } catch (error) {
      detailEl.replaceChildren(element('div', 'error', String(error)));
    }
  }

  function selectRoot(id, button) {
    stopPlayback(); markSelectedRoot(id);
    treeTab.disabled = historyTab.disabled = playHistoryTab.disabled = false;
    setActiveTab(treeTab); load('/api/diff?root=' + encodeURIComponent(id), renderComparison);
  }

  async function playLineage() {
    if (playing) { stopPlayback(); return; }
    if (!selected) return;
    playing = true; const token = ++playbackToken;
    playHistoryTab.textContent = '■ Stop'; setActiveTab(playHistoryTab);
    detailEl.replaceChildren(element('div', 'loading', 'Loading snapshot lineage…'));
    try {
      const history = await fetchJson('/api/history?root=' + encodeURIComponent(selected));
      playbackFrames = [...history].reverse();
      for (let index = 0; index < playbackFrames.length; index += 1) {
        if (token !== playbackToken) return;
        await showPlaybackFrame(index);
        if (token !== playbackToken) return;
        if (index < playbackFrames.length - 1) {
          await new Promise(resolve => setTimeout(resolve, 400));
        }
      }
    } catch (error) {
      detailEl.replaceChildren(element('div', 'error', String(error)));
    } finally {
      if (token === playbackToken) stopPlayback();
    }
  }

  async function showPlaybackFrame(index) {
    const requestToken = ++frameRequestToken;
    playbackFrameIndex = Math.max(0, Math.min(index, playbackFrames.length - 1));
    const id = rootId(playbackFrames[playbackFrameIndex]); markSelectedRoot(id);
    try {
      let diff = diffCache.get(id);
      if (!diff) {
        diff = await fetchJson('/api/diff?root=' + encodeURIComponent(id));
        diffCache.set(id, diff);
      }
      if (requestToken !== frameRequestToken) return;
      renderComparison(diff, `Snapshot ${playbackFrameIndex + 1} of ${playbackFrames.length}`);
    } catch (error) {
      if (requestToken === frameRequestToken) {
        detailEl.replaceChildren(element('div', 'error', String(error)));
      }
    }
  }

  fetch('/api/roots').then(response => response.json()).then(data => {
    const roots = Array.isArray(data) ? data : (data.roots || []);
    rootsEl.className = '';
    rootsEl.replaceChildren(...roots.map(root => {
      const id = rootId(root); const button = document.createElement('button');
      button.append(element('span', 'snapshot-id', shortId(id)));
      button.append(element('span', 'snapshot-time', typeof root === 'object' ? date(root.created_at) : ''));
      button.dataset.rootId = id;
      button.title = typeof root === 'string' ? root : pretty(root);
      button.onclick = () => selectRoot(id, button); return button;
    }));
    if (!roots.length) rootsEl.textContent = 'No roots found in this namespace.';
    else rootsEl.querySelector('button').click();
  }).catch(error => { rootsEl.className = 'error'; rootsEl.textContent = String(error); });

  treeTab.onclick = () => { if (selected) { stopPlayback(); setActiveTab(treeTab); load('/api/diff?root=' + encodeURIComponent(selected), renderComparison); } };
  historyTab.onclick = () => { if (selected) { stopPlayback(); setActiveTab(historyTab); load('/api/history?root=' + encodeURIComponent(selected), renderHistory); } };
  allHistoryTab.onclick = () => { stopPlayback(); setActiveTab(allHistoryTab); load('/api/history', renderHistory); };
  playHistoryTab.onclick = playLineage;
</script>
</body>
</html>
"""


class ViewerHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying the viewer service used by request handlers."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], viewer: HistoryViewer) -> None:
        self.viewer = viewer
        super().__init__(address, ViewerRequestHandler)


class ViewerRequestHandler(BaseHTTPRequestHandler):
    @property
    def viewer(self) -> HistoryViewer:
        return cast(ViewerHTTPServer, self.server).viewer

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(_json_value(value), indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _required_root(self, query: dict[str, list[str]]) -> str | None:
        root = query.get("root", [""])[0]
        if not root:
            self._json({"error": "Missing required 'root' query parameter"}, HTTPStatus.BAD_REQUEST)
            return None
        return root

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        request = urlsplit(self.path)
        query = parse_qs(request.query)
        try:
            if request.path == "/":
                self._send(HTTPStatus.OK, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif request.path == "/api/roots":
                self._json(_list_roots(self.viewer))
            elif request.path == "/api/tree":
                root = self._required_root(query)
                if root is not None:
                    self._json(_get_tree(self.viewer, root))
            elif request.path == "/api/history":
                root = query.get("root", [None])[0]
                self._json(_get_history(self.viewer, root))
            elif request.path == "/api/diff":
                root = self._required_root(query)
                if root is not None:
                    self._json(_get_diff(self.viewer, root))
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as error:  # Service/domain errors become useful API errors.
            logger.exception("Viewer request failed: %s", self.path)
            self._json({"error": str(error), "type": type(error).__name__}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.client_address[0], format % args)


def create_server(viewer: HistoryViewer, host: str = "127.0.0.1", port: int = 8765) -> ViewerHTTPServer:
    return ViewerHTTPServer((host, port), viewer)


def serve(viewer: HistoryViewer, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve until interrupted."""
    server = create_server(viewer, host, port)
    logger.info("Viewer listening at http://%s:%d", host, server.server_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
