"""Fipsy TUI — IPFS content sharing and discovery dashboard."""

import platform
import subprocess
import webbrowser
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import (
    Footer,
    Header,
    ProgressBar,
    Static,
    TabbedContent,
    TabPane,
)

from fipsy import db
from fipsy.tui.screens import AddDirectoryScreen, ConfirmScreen, IpfsErrorScreen
from fipsy.tui.widgets import BrowseTable, PeerTable, PublishedTable
from fipsy.tui import workers


TRUNCATE_LEN = 12


def _trunc(s: str, n: int = TRUNCATE_LEN) -> str:
    return s[:n] + ".." if len(s) > n + 2 else s


class FipsyApp(App):
    """IPFS content sharing and discovery TUI."""

    TITLE = "fipsy"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("s", "scan", "Scan", show=True),
        Binding("a", "add_directory", "Add", show=True),
        Binding("shift+p", "publish_all", "Publish", show=True),
        Binding("p", "pin", "Pin", show=True),
        Binding("d", "remove", "Remove", show=True),
        Binding("o", "open_browser", "Open", show=True),
        Binding("r", "refresh_browse", "Refresh", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._scan_total = 0
        self._scan_done = 0
        self._publish_total = 0
        self._publish_done = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent("Network", "My Content", "Browse", id="tabs"):
            with TabPane("Network", id="network-tab"):
                yield Static("No peers scanned yet. Press [bold]s[/] to scan.", id="network-status", classes="status-bar")
                yield PeerTable(id="peer-table")
                with Vertical(id="scan-progress", classes="progress-container"):
                    yield ProgressBar(total=100, id="scan-bar")

            with TabPane("My Content", id="content-tab"):
                yield Static("Press [bold]a[/] to add a directory.", id="content-status", classes="status-bar")
                yield PublishedTable(id="published-table")
                with Vertical(id="publish-progress", classes="progress-container"):
                    yield ProgressBar(total=100, id="publish-bar")

            with TabPane("Browse", id="browse-tab"):
                yield Static("Press [bold]r[/] to refresh.", id="browse-status", classes="status-bar")
                yield BrowseTable(id="browse-table")
        yield Footer()

    def on_mount(self) -> None:
        self._check_ipfs()

    def _check_ipfs(self) -> None:
        installed, running = workers.check_ipfs()
        if not installed or not running:
            self.push_screen(IpfsErrorScreen(installed), self._on_ipfs_error_dismiss)
        else:
            db.init_db()
            self._load_published()

    def _on_ipfs_error_dismiss(self, retry: bool) -> None:
        if retry:
            self._check_ipfs()
        else:
            self.exit()

    # ── Network Tab ──────────────────────────────────────────────

    def action_scan(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "network-tab"
        self._start_scan()

    def _start_scan(self) -> None:
        self._scan_total = 0
        self._scan_done = 0

        progress = self.query_one("#scan-progress")
        progress.add_class("visible")
        bar = self.query_one("#scan-bar", ProgressBar)
        bar.update(total=100, progress=0)

        table = self.query_one("#peer-table", PeerTable)
        table.clear()

        status = self.query_one("#network-status", Static)
        status.update("Scanning...")

        self.run_worker(self._scan_worker, thread=True, exclusive=True, group="scan")

    def _scan_worker(self) -> None:
        for item in workers.scan_peers_iter():
            if isinstance(item, int):
                self._scan_total = item
                if item == 0:
                    self.call_from_thread(self._scan_no_peers)
                    return
                self.call_from_thread(self._scan_update_status, f"Scanning {item} peer(s)...")
            else:
                self._scan_done += 1
                self.call_from_thread(self._scan_add_result, item)
                if self._scan_total > 0:
                    pct = (self._scan_done / self._scan_total) * 100
                    self.call_from_thread(self._scan_update_progress, pct)

        self.call_from_thread(self._scan_complete)

    def _scan_no_peers(self) -> None:
        self.query_one("#network-status", Static).update("No peers found.")
        self.query_one("#scan-progress").remove_class("visible")

    def _scan_update_status(self, msg: str) -> None:
        self.query_one("#network-status", Static).update(msg)

    def _scan_update_progress(self, pct: float) -> None:
        self.query_one("#scan-bar", ProgressBar).update(progress=pct)

    def _scan_add_result(self, result: workers.ScanResult) -> None:
        table = self.query_one("#peer-table", PeerTable)
        for entry in result.entries:
            table.add_row(
                _trunc(entry.peer_id),
                entry.name,
                _trunc(entry.ipns_name),
                _trunc(entry.cid) if entry.cid else "unresolved",
                key=f"{entry.peer_id}:{entry.ipns_name}",
            )

    def _scan_complete(self) -> None:
        table = self.query_one("#peer-table", PeerTable)
        count = table.row_count
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#network-status", Static).update(
            f"{count} entries from peers  |  Last scan: {now}"
        )
        self.query_one("#scan-progress").remove_class("visible")
        self.notify(f"Scan complete: {count} entries found")

    # ── My Content Tab ───────────────────────────────────────────

    def _load_published(self) -> None:
        """Load published directories into the table."""
        table = self.query_one("#published-table", PublishedTable)
        table.clear()

        published = workers.get_published()
        status = self.query_one("#content-status", Static)

        if not published:
            status.update("No published directories. Press [bold]a[/] to add one.")
            return

        status.update(f"{len(published)} published directory(s)")
        for entry in published:
            added = entry["added"][:10] if entry.get("added") else ""
            table.add_row(
                entry["key"],
                _trunc(entry["path"], 30),
                entry["key"],
                added,
                key=entry["path"],
            )

    def action_add_directory(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "content-tab"
        self.push_screen(AddDirectoryScreen(), self._on_add_dismiss)

    def _on_add_dismiss(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        path, name = result
        self.notify(f"Adding {name}...")
        self.run_worker(
            lambda: self._add_worker(path, name), thread=True, group="add"
        )

    def _add_worker(self, path: str, name: str) -> None:
        try:
            result = workers.add_directory(path, name)
            self.call_from_thread(self._on_add_complete, result)
        except Exception as e:
            self.call_from_thread(self.notify, f"Add failed: {e}", severity="error")

    def _on_add_complete(self, result: workers.PublishResult) -> None:
        if result.error:
            self.notify(f"Add failed: {result.error}", severity="error")
        else:
            self.notify(f"Added {result.key} → ipns://{_trunc(result.ipns_name)}")
            self._load_published()

    def action_remove(self) -> None:
        table = self.query_one("#published-table", PublishedTable)
        if table.row_count == 0:
            return

        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return

        path = str(row_key)
        self.push_screen(
            ConfirmScreen(f"Remove {path} from published list?"),
            lambda confirmed: self._on_remove_confirm(confirmed, path),
        )

    def _on_remove_confirm(self, confirmed: bool, path: str) -> None:
        if not confirmed:
            return
        workers.remove_published(path)
        self._load_published()
        self.notify("Removed from published list")

    def action_publish_all(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "content-tab"

        self._publish_total = 0
        self._publish_done = 0

        progress = self.query_one("#publish-progress")
        progress.add_class("visible")
        bar = self.query_one("#publish-bar", ProgressBar)
        bar.update(total=100, progress=0)

        status = self.query_one("#content-status", Static)
        status.update("Publishing...")

        self.run_worker(self._publish_worker, thread=True, exclusive=True, group="publish")

    def _publish_worker(self) -> None:
        for item in workers.publish_all_iter():
            if isinstance(item, int):
                self._publish_total = item
                if item == 0:
                    self.call_from_thread(self._publish_empty)
                    return
                self.call_from_thread(
                    self._publish_update_status, f"Publishing {item} directory(s)..."
                )
            else:
                self._publish_done += 1
                if item.error:
                    self.call_from_thread(
                        self.notify, f"{item.key}: {item.error}", severity="error"
                    )
                else:
                    self.call_from_thread(
                        self.notify, f"Published {item.key}"
                    )

                if self._publish_total > 0:
                    pct = (self._publish_done / self._publish_total) * 100
                    self.call_from_thread(self._publish_update_progress, pct)

        self.call_from_thread(self._publish_complete)

    def _publish_empty(self) -> None:
        self.notify("No directories to publish", severity="warning")
        self.query_one("#publish-progress").remove_class("visible")
        self.query_one("#content-status", Static).update(
            "No published directories. Press [bold]a[/] to add one."
        )

    def _publish_update_status(self, msg: str) -> None:
        self.query_one("#content-status", Static).update(msg)

    def _publish_update_progress(self, pct: float) -> None:
        self.query_one("#publish-bar", ProgressBar).update(progress=pct)

    def _publish_complete(self) -> None:
        self.query_one("#publish-progress").remove_class("visible")
        self._load_published()
        self.notify("Publish complete!")

    # ── Browse Tab ───────────────────────────────────────────────

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "browse-tab":
            self._refresh_browse()

    def action_refresh_browse(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "browse-tab"
        self._refresh_browse()

    def _refresh_browse(self) -> None:
        status = self.query_one("#browse-status", Static)
        status.update("Loading...")
        self.run_worker(self._browse_worker, thread=True, exclusive=True, group="browse")

    def _browse_worker(self) -> None:
        entries = workers.get_browse_entries()
        self.call_from_thread(self._browse_loaded, entries)

    def _browse_loaded(self, entries: list[workers.BrowseEntry]) -> None:
        table = self.query_one("#browse-table", BrowseTable)
        table.clear()

        for entry in entries:
            table.add_row(
                entry.name,
                entry.source,
                _trunc(entry.ipns_name),
                "yes" if entry.pinned else "",
                key=entry.ipns_name,
            )

        status = self.query_one("#browse-status", Static)
        status.update(f"{len(entries)} IPNS key(s)")

    def action_pin(self) -> None:
        # Pin works on Network tab (pin by CID) or Browse tab (pin by IPNS)
        tabs = self.query_one("#tabs", TabbedContent)
        active = tabs.active

        if active == "network-tab":
            self._pin_from_network()
        elif active == "browse-tab":
            self._pin_from_browse()

    def _pin_from_network(self) -> None:
        table = self.query_one("#peer-table", PeerTable)
        if table.row_count == 0:
            return

        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return

        cid_cell = table.get_cell_at(table.cursor_coordinate._replace(column=3))
        if cid_cell == "unresolved":
            self.notify("Cannot pin unresolved content", severity="warning")
            return

        self.notify(f"Pinning {cid_cell}...")
        self.run_worker(
            lambda: self._pin_worker(str(cid_cell)), thread=True, group="pin"
        )

    def _pin_from_browse(self) -> None:
        table = self.query_one("#browse-table", BrowseTable)
        if table.row_count == 0:
            return

        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return

        ipns_name = str(row_key)
        self.notify(f"Resolving and pinning {_trunc(ipns_name)}...")
        self.run_worker(
            lambda: self._pin_ipns_worker(ipns_name), thread=True, group="pin"
        )

    def _pin_worker(self, cid: str) -> None:
        success = workers.pin_cid(cid)
        if success:
            self.call_from_thread(self.notify, f"Pinned {_trunc(cid)}")
        else:
            self.call_from_thread(self.notify, f"Pin failed: {_trunc(cid)}", severity="error")

    def _pin_ipns_worker(self, ipns_name: str) -> None:
        from fipsy import ipfs as _ipfs
        import subprocess

        try:
            resolved = _ipfs.name_resolve(ipns_name)
            cid = resolved.split("/")[-1]
            _ipfs.pin_add(cid)
            self.call_from_thread(self.notify, f"Pinned {_trunc(cid)}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.call_from_thread(self.notify, f"Pin failed for {_trunc(ipns_name)}", severity="error")

    def action_open_browser(self) -> None:
        table = self.query_one("#browse-table", BrowseTable)
        if table.row_count == 0:
            return

        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return

        ipns_name = str(row_key)
        self._open_ipns(ipns_name)

    def on_data_table_row_selected(self, event: BrowseTable.RowSelected) -> None:
        if isinstance(event.data_table, BrowseTable):
            ipns_name = str(event.row_key.value)
            self._open_ipns(ipns_name)
        elif isinstance(event.data_table, PublishedTable):
            path = str(event.row_key.value)
            self._open_directory(path)

    def _open_ipns(self, ipns_name: str) -> None:
        url = f"ipns://{ipns_name}"
        webbrowser.open(url)
        self.notify(f"Opening {_trunc(ipns_name)}")

    def _open_directory(self, path: str) -> None:
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["open", path])
            elif system == "Windows":
                subprocess.Popen(["explorer", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self.notify(f"Opened {_trunc(path, 30)}")
        except FileNotFoundError:
            self.notify("Could not open directory", severity="error")

    def action_help(self) -> None:
        help_text = (
            "[bold]Keyboard Shortcuts[/]\n\n"
            "[bold]s[/]  Scan network for peers\n"
            "[bold]a[/]  Add directory\n"
            "[bold]P[/]  Publish all directories\n"
            "[bold]p[/]  Pin selected content\n"
            "[bold]d[/]  Remove selected from published\n"
            "[bold]o[/]  Open in browser (Browse tab)\n"
            "[bold]r[/]  Refresh browse list\n"
            "[bold]j/k[/]  Navigate rows\n"
            "[bold]Tab/Shift+Tab[/]  Switch tabs\n"
            "[bold]q[/]  Quit"
        )
        self.notify(help_text, timeout=10)


def run() -> None:
    app = FipsyApp()
    app.run()
