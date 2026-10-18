from types import SimpleNamespace

from lou_codi_pdf_converter.app import Application


class _FakeWindow:
    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.log = log
        self._w = f".{name}"
        self.tk = SimpleNamespace(call=self._tk_call)

    def _tk_call(self, *args: object) -> None:
        self.log.append(f"{self.name}:tk:{args[1]}")

    def update_idletasks(self) -> None:
        self.log.append(f"{self.name}:update")

    def geometry(self, value: str | None = None) -> str:
        if value is not None:
            self.log.append(f"{self.name}:geometry")
        return "1000x700+10+10"

    def state(self) -> str:
        return "normal"

    def wm_group(self, _parent: object) -> None:
        self.log.append(f"{self.name}:group")

    def grab_release(self) -> None:
        self.log.append(f"{self.name}:release")

    def iconphoto(self, *_args: object) -> None:
        self.log.append(f"{self.name}:icon")

    def deiconify(self) -> None:
        self.log.append(f"{self.name}:show")

    def withdraw(self) -> None:
        self.log.append(f"{self.name}:hide")

    def iconify(self) -> None:
        self.log.append(f"{self.name}:iconify")

    def lift(self) -> None:
        self.log.append(f"{self.name}:lift")

    def focus_force(self) -> None:
        self.log.append(f"{self.name}:focus")

    def wait_window(self, _window: object) -> None:
        self.log.append(f"{self.name}:wait")

    def winfo_exists(self) -> bool:
        return True


def test_workspace_is_detached_and_shown_before_parent_is_hidden() -> None:
    log: list[str] = []
    application = SimpleNamespace(app_icon=object())
    previous = _FakeWindow("home", log)
    workspace = _FakeWindow("studio", log)

    Application._replace_workspace(application, previous, workspace)

    detach = log.index("studio:tk:transient")
    show = log.index("studio:show")
    hide_parent = log.index("home:hide")
    assert detach < hide_parent
    assert show < hide_parent
    assert "studio:tk:group" in log


def test_restoring_launcher_redirects_focus_to_active_workspace() -> None:
    log: list[str] = []
    workspace = _FakeWindow("studio", log)
    workspace.winfo_viewable = lambda: True
    application = SimpleNamespace(
        _active_workspace=workspace,
        _workspace_focus_redirect_pending=False,
        iconify=lambda: log.append("home:iconify"),
    )
    application.after_idle = lambda callback: callback()

    Application._redirect_to_active_workspace(application)

    assert log == ["home:iconify", "studio:show", "studio:lift", "studio:focus"]
