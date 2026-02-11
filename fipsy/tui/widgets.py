"""DataTable subclasses for each tab."""

from textual.widgets import DataTable


class PeerTable(DataTable):
    """Network tab — discovered peers and their content."""

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
    ]

    def on_mount(self) -> None:
        self.add_columns("Peer", "Name", "IPNS", "CID")
        self.cursor_type = "row"


class PublishedTable(DataTable):
    """My Content tab — published directories."""

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
    ]

    def on_mount(self) -> None:
        self.add_columns("Name", "Path", "Key", "Added")
        self.cursor_type = "row"


class BrowseTable(DataTable):
    """Browse tab — all known IPNS keys."""

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
    ]

    def on_mount(self) -> None:
        self.add_columns("Name", "Source", "IPNS", "Pinned")
        self.cursor_type = "row"
