"""Modal screens for the TUI."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class AddDirectoryScreen(ModalScreen[tuple[str, str] | None]):
    """Modal to add a directory to IPFS."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Static("Add Directory", id="title")
            yield Static("Path:")
            yield Input(placeholder="/path/to/directory", id="path-input")
            yield Static("Name:")
            yield Input(placeholder="my-content", id="name-input")
            with Horizontal(classes="button-row"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Add", variant="primary", id="add")

    def on_mount(self) -> None:
        self.query_one("#path-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "path-input":
            path = event.value.strip()
            name_input = self.query_one("#name-input", Input)
            if path and not name_input.value:
                # Auto-fill name from path basename
                from pathlib import Path

                basename = Path(path).name
                if basename:
                    name_input.value = basename

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "add":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "path-input":
            self.query_one("#name-input", Input).focus()
        elif event.input.id == "name-input":
            self._submit()

    def _submit(self) -> None:
        path = self.query_one("#path-input", Input).value.strip()
        name = self.query_one("#name-input", Input).value.strip()
        if not path:
            self.notify("Path is required", severity="error")
            return
        if not name:
            name = path.rstrip("/").split("/")[-1]
        self.dismiss((path, name))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """Simple yes/no confirmation dialog."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Static("Confirm", id="title")
            yield Static(self._message)
            with Horizontal(classes="button-row"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Confirm", variant="warning", id="confirm")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class IpfsErrorScreen(ModalScreen[bool]):
    """Shown when IPFS daemon is not running."""

    def __init__(self, installed: bool) -> None:
        super().__init__()
        self._installed = installed

    BINDINGS = [("escape", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="error-dialog"):
            yield Static("IPFS Not Available", id="error-title")
            if not self._installed:
                yield Static(
                    "IPFS is not installed.\nInstall it from https://docs.ipfs.tech/install/",
                    id="error-message",
                )
            else:
                yield Static(
                    "IPFS daemon is not running.\nStart it with: ipfs daemon",
                    id="error-message",
                )
            with Horizontal(classes="button-row"):
                yield Button("Quit", variant="default", id="quit")
                yield Button("Retry", variant="primary", id="retry")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "retry")

    def action_quit(self) -> None:
        self.dismiss(False)
