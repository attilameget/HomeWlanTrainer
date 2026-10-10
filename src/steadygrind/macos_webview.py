"""macOS steadyGrind window: system WebKit, no browser chrome.

The menu-bar agent owns this window. The ride engine stays in the server
process, so closing the window only hides the UI. Phone browsers are unchanged.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# NSWindowStyleMaskFullScreen. A full-screen window owns its own desktop.
_FULLSCREEN_STYLE_MASK = 1 << 14

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_INLINE_SCHEMES = frozenset({"about", "data", "blob", "javascript"})
_CANCELLED = -999  # NSURLErrorCancelled

_OFFLINE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>steadyGrind</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #121417;
      color: #e8eaed;
      font: 16px -apple-system, BlinkMacSystemFont, sans-serif;
    }
    p { max-width: 28rem; text-align: center; line-height: 1.45; }
  </style>
</head>
<body>
  <p>steadyGrind is not responding on this Mac. Quit it from the menu bar and open it again.</p>
</body>
</html>
"""

_pending: list[object] = []
_bound = False
_webkit_ok = False
_controller: object | None = None
_Invoker = None  # type: ignore[assignment]


def is_local_ui_url(url: str | None, *, port: int) -> bool:
    """True when a navigation should stay inside the steadyGrind window."""
    if url is None:
        return True
    raw = url.strip()
    if raw == "":
        return True
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme in _INLINE_SCHEMES:
        return True
    if scheme == "" and "://" not in raw:
        return True
    if scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().strip("[]")
    if host not in _LOCAL_HOSTS:
        return False
    if parsed.port is None:
        effective = 443 if scheme == "https" else 80
    else:
        effective = parsed.port
    return effective == port


def should_download_response(*, url: str, mime: str, content_disposition: str) -> bool:
    """True for FIT attachments and other files the window should not render."""
    if "attachment" in content_disposition.lower():
        return True
    path = urlparse(url).path
    if path.startswith("/api/rides/") and path.endswith("/fit"):
        return True
    return mime.lower() in {
        "application/octet-stream",
        "application/vnd.ant.fit",
    } and path.endswith(".fit")


def safe_download_name(suggested: str | None) -> str:
    raw = (suggested or "").replace("\\", "/").strip()
    name = Path(raw).name.strip()
    if name in {"", ".", ".."}:
        return "download"
    return name


def unique_download_path(directory: Path, filename: str) -> Path:
    name = safe_download_name(filename)
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 2
    while index < 10000:
        nxt = directory / f"{stem}-{index}{suffix}"
        if not nxt.exists():
            return nxt
        index += 1
    raise RuntimeError(f"could not allocate a download name for {name}")


def webkit_available() -> bool:
    """True when this Mac can host the UI in a WebKit window."""
    return _bind()


def present_ui(url: str, *, port: int = 8080) -> bool:
    """Show the steadyGrind window. False when WebKit cannot be loaded."""
    if not _bind():
        return False

    def go() -> None:
        try:
            _singleton().show(url, port=port)
        except Exception:
            logger.exception("WebKit window failed; opening the default browser")
            open_in_default_browser(url)

    _run_on_main(go)
    return True


def reload_ui() -> bool:
    """Reload the page in the existing window, opening it if needed."""
    if not _bind():
        return False

    def go() -> None:
        try:
            _singleton().reload()
        except Exception:
            logger.exception("WebKit reload failed")

    _run_on_main(go)
    return True


_menus_installed = False


def install_app_menus(target: object) -> bool:
    """Install Edit / View menus so text fields and Reload work in the window."""
    global _menus_installed
    if not _bind():
        return False
    if _menus_installed:
        return True
    from AppKit import (  # type: ignore[import-untyped]
        NSApp,
        NSApplication,
        NSMenu,
        NSMenuItem,
    )

    app = NSApplication.sharedApplication()

    main = NSMenu.alloc().init()

    app_menu = NSMenu.alloc().initWithTitle_("steadyGrind")
    about = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "About steadyGrind", "orderFrontStandardAboutPanel:", ""
    )
    app_menu.addItem_(about)
    app_menu.addItem_(NSMenuItem.separatorItem())
    hide = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Hide steadyGrind", "hide:", "h"
    )
    hide.setTarget_(NSApp)
    app_menu.addItem_(hide)
    app_menu.addItem_(NSMenuItem.separatorItem())
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit steadyGrind", "quit:", "q"
    )
    quit_item.setTarget_(target)
    app_menu.addItem_(quit_item)
    app_item = NSMenuItem.alloc().init()
    app_item.setSubmenu_(app_menu)
    main.addItem_(app_item)

    edit = NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in (
        ("Undo", "undo:", "z"),
        ("Redo", "redo:", "Z"),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ):
        edit.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key))
    edit_item = NSMenuItem.alloc().init()
    edit_item.setSubmenu_(edit)
    main.addItem_(edit_item)

    view = NSMenu.alloc().initWithTitle_("View")
    reload_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Reload", "reloadUI:", "r"
    )
    reload_item.setTarget_(target)
    view.addItem_(reload_item)
    view_item = NSMenuItem.alloc().init()
    view_item.setSubmenu_(view)
    main.addItem_(view_item)

    window_menu = NSMenu.alloc().initWithTitle_("Window")
    window_menu.addItem_(
        NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Minimize", "performMiniaturize:", "m")
    )
    window_menu.addItem_(
        NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Zoom", "performZoom:", "")
    )
    window_item = NSMenuItem.alloc().init()
    window_item.setSubmenu_(window_menu)
    main.addItem_(window_item)

    app.setMainMenu_(main)
    app.setWindowsMenu_(window_menu)
    _menus_installed = True
    return True


def open_in_default_browser(url: str) -> None:
    subprocess.run(["open", url], check=False)


def _bind() -> bool:
    global _bound, _webkit_ok, _Invoker
    if _bound:
        return _webkit_ok
    _bound = True
    if sys.platform != "darwin":
        return False
    try:
        import AppKit  # type: ignore[import-untyped]  # noqa: F401
        import Foundation  # type: ignore[import-untyped]
        import WebKit  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        logger.info("WebKit is not installed; the UI will open in the default browser")
        return False

    class MainInvoker(Foundation.NSObject):
        def initWithCallable_(self, fn):  # noqa: N802
            self = self.init()
            if self is None:
                return None
            self.fn = fn
            return self

        def invoke_(self, _arg) -> None:  # noqa: N802
            fn = getattr(self, "fn", None)
            self.fn = None
            try:
                _pending.remove(self)
            except ValueError:
                pass
            if fn is not None:
                fn()

    _Invoker = MainInvoker
    _webkit_ok = True
    return True


def _run_on_main(fn) -> None:
    from Foundation import NSThread  # type: ignore[import-untyped]

    if NSThread.isMainThread():
        fn()
        return
    if _Invoker is None:
        fn()
        return
    invoker = _Invoker.alloc().initWithCallable_(fn)
    _pending.append(invoker)
    invoker.performSelectorOnMainThread_withObject_waitUntilDone_("invoke:", None, False)


class _UiController:
    def __init__(self) -> None:
        self.url = "http://127.0.0.1:8080"
        self.port = 8080
        self.window = None
        self.webview = None
        self.delegate = None

    def show(self, url: str, *, port: int) -> None:
        self.url = url
        self.port = port
        self._ensure_window()
        self._become_regular_app()
        self.window.makeKeyAndOrderFront_(None)
        from AppKit import NSApplication  # type: ignore[import-untyped]

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def reload(self) -> None:
        """Load the UI again with an empty cache. A restart does the same."""
        if self.window is None:
            self.show(self.url, port=self.port)
            return
        self._mount_webview()
        self._become_regular_app()
        self.window.makeKeyAndOrderFront_(None)
        from AppKit import NSApplication  # type: ignore[import-untyped]

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def _ensure_window(self) -> None:
        if self.window is not None:
            return
        import AppKit  # type: ignore[import-untyped]
        import Foundation  # type: ignore[import-untyped]

        frame = _default_frame(AppKit, Foundation)
        style = _window_style(AppKit)
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("steadyGrind")
        window.setReleasedWhenClosed_(False)
        window.setContentMinSize_(Foundation.NSMakeSize(880, 640))
        window.setFrameAutosaveName_("steadyGrindMain")
        window.setCollectionBehavior_(
            getattr(AppKit, "NSWindowCollectionBehaviorFullScreenPrimary", 1 << 7)
        )
        self.window = window
        self._mount_webview()

    def _mount_webview(self) -> None:
        """Install a new web view and load the UI, ignoring any cached page."""
        import AppKit  # type: ignore[import-untyped]
        import WebKit  # type: ignore[import-untyped]

        _install_delegate()
        if self.window is None:
            return
        config = WebKit.WKWebViewConfiguration.alloc().init()
        try:
            config.setWebsiteDataStore_(WebKit.WKWebsiteDataStore.nonPersistentDataStore())
        except Exception:
            logger.debug("non-persistent website data store unavailable", exc_info=True)
        try:
            config.preferences().setValue_forKey_(True, "developerExtrasEnabled")
        except Exception:
            logger.debug("developer extras unavailable", exc_info=True)
        content = self.window.contentView()
        bounds = content.bounds() if content is not None else self.window.frame()
        webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(bounds, config)
        webview.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        try:
            webview.setAllowsBackForwardNavigationGestures_(True)
        except Exception:
            logger.debug("back-forward gestures unavailable", exc_info=True)

        if self.delegate is None:
            delegate = _WebDelegate.alloc().init()
            delegate.controller = self
            self.delegate = delegate
            self.window.setDelegate_(delegate)
        webview.setNavigationDelegate_(self.delegate)
        webview.setUIDelegate_(self.delegate)
        self.window.setContentView_(webview)
        webview.loadRequest_(_fresh_request(self.url))
        self.webview = webview

    def _become_regular_app(self) -> None:
        import AppKit  # type: ignore[import-untyped]
        import Foundation  # type: ignore[import-untyped]

        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        Foundation.NSProcessInfo.processInfo().setProcessName_("steadyGrind")
        _apply_dock_icon(AppKit)


def _fresh_request(url: str):
    """Document request that bypasses the WebKit cache."""
    import Foundation  # type: ignore[import-untyped]

    request = Foundation.NSMutableURLRequest.requestWithURL_(
        Foundation.NSURL.URLWithString_(url)
    )
    policy = getattr(Foundation, "NSURLRequestReloadIgnoringLocalCacheData", 1)
    request.setCachePolicy_(policy)
    return request


def _default_frame(appkit, foundation):
    screen = appkit.NSScreen.mainScreen()
    visible = screen.visibleFrame() if screen is not None else foundation.NSMakeRect(0, 0, 1440, 900)
    width, height = 1280.0, 800.0
    if visible.size.width < width + 48:
        width = max(880.0, visible.size.width - 48)
    if visible.size.height < height + 48:
        height = max(640.0, visible.size.height - 48)
    x = visible.origin.x + (visible.size.width - width) / 2.0
    y = visible.origin.y + (visible.size.height - height) / 2.0
    return foundation.NSMakeRect(x, y, width, height)


def _window_style(appkit) -> int:
    parts = []
    for name, fallback in (
        ("NSWindowStyleMaskTitled", 1 << 0),
        ("NSWindowStyleMaskClosable", 1 << 1),
        ("NSWindowStyleMaskMiniaturizable", 1 << 2),
        ("NSWindowStyleMaskResizable", 1 << 3),
    ):
        parts.append(getattr(appkit, name, fallback))
    mask = 0
    for part in parts:
        mask |= int(part)
    return mask


def _apply_dock_icon(appkit) -> None:
    for path in _icon_candidates():
        if not path.is_file():
            continue
        image = appkit.NSImage.alloc().initWithContentsOfFile_(str(path))
        if image is None:
            continue
        appkit.NSApplication.sharedApplication().setApplicationIconImage_(image)
        return


def _icon_candidates() -> list[Path]:
    found: list[Path] = []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        found.append(exe.parent.parent / "AppIcon.icns")
    found.append(Path(__file__).resolve().parents[2] / "deploy" / "macos" / "AppIcon.icns")
    return found


def window_is_fullscreen(style_mask: int, *, fullscreen_mask: int = _FULLSCREEN_STYLE_MASK) -> bool:
    """True when the window is the full-screen desktop, not a normal window."""
    return bool(int(style_mask) & int(fullscreen_mask))


def window_close_action(*, fullscreen: bool, leaving_fullscreen: bool) -> str:
    """What the red close button does: ignore, leave-fullscreen, or quit.

    A full-screen window owns a desktop. Quitting there leaves a black space,
    so the app leaves that desktop first and quits once macOS has dropped it.
    """
    if leaving_fullscreen:
        return "ignore"
    if fullscreen:
        return "leave-fullscreen"
    return "quit"


def _action_url(action) -> str | None:
    try:
        request = action.request()
        url = request.URL() if request is not None else None
        if url is None:
            return None
        return str(url.absoluteString())
    except Exception:
        return None


def _wants_download(action) -> bool:
    try:
        return bool(action.shouldPerformDownload())
    except Exception:
        return False


def _header(response, name: str) -> str:
    if response is None:
        return ""
    try:
        headers = response.allHeaderFields()
    except Exception:
        return ""
    if headers is None:
        return ""
    wanted = name.lower()
    try:
        keys = list(headers)
    except Exception:
        keys = []
    for key in keys:
        if str(key).lower() == wanted:
            value = headers.objectForKey_(key)
            return "" if value is None else str(value)
    return ""


def _policy(module, name: str, fallback: int) -> int:
    return int(getattr(module, name, fallback))


# Built at first use on macOS. A class statement at import would require AppKit
# on Linux, where the agent never runs.
class _WebDelegate:  # placeholder replaced by _install_delegate on darwin
    pass


_delegate_ready = False


def _install_delegate() -> None:
    global _WebDelegate, _delegate_ready
    if _delegate_ready:
        return
    import AppKit  # type: ignore[import-untyped]
    import Foundation  # type: ignore[import-untyped]
    import WebKit  # type: ignore[import-untyped]

    allow_action = _policy(WebKit, "WKNavigationActionPolicyAllow", 1)
    cancel_action = _policy(WebKit, "WKNavigationActionPolicyCancel", 0)
    download_action = _policy(WebKit, "WKNavigationActionPolicyDownload", 2)
    allow_response = _policy(WebKit, "WKNavigationResponsePolicyAllow", 1)
    download_response = _policy(WebKit, "WKNavigationResponsePolicyDownload", 2)
    first_button = int(getattr(AppKit, "NSAlertFirstButtonReturn", 1000))

    class WebDelegate(AppKit.NSObject):
        controller = None

        def _quit_app(self) -> None:
            AppKit.NSApplication.sharedApplication().terminate_(None)

        def windowShouldClose_(self, sender) -> bool:  # noqa: N802
            # Quit, so the Dock icon goes away. A full-screen window owns a
            # desktop; quitting there leaves a black space. Leave that desktop
            # first, then quit once macOS has dropped it.
            fullscreen_mask = int(getattr(AppKit, "NSWindowStyleMaskFullScreen", _FULLSCREEN_STYLE_MASK))
            try:
                mask = int(sender.styleMask())
            except Exception:
                mask = 0
            action = window_close_action(
                fullscreen=window_is_fullscreen(mask, fullscreen_mask=fullscreen_mask),
                leaving_fullscreen=bool(getattr(self, "quit_after_fullscreen_exit", False)),
            )
            if action == "leave-fullscreen":
                self.quit_after_fullscreen_exit = True
                sender.toggleFullScreen_(None)
            elif action == "quit":
                self._quit_app()
            return False

        def windowDidExitFullScreen_(self, notification) -> None:  # noqa: N802
            if not getattr(self, "quit_after_fullscreen_exit", False):
                return
            self.quit_after_fullscreen_exit = False
            self._quit_app()

        def windowDidFailToExitFullScreen_(self, notification) -> None:  # noqa: N802
            self.quit_after_fullscreen_exit = False

        def webView_decidePolicyForNavigationAction_decisionHandler_(  # noqa: N802
            self, webview, action, handler
        ) -> None:
            policy = allow_action
            try:
                if _wants_download(action):
                    policy = download_action
                else:
                    url = _action_url(action)
                    port = self.controller.port if self.controller is not None else 8080
                    if not is_local_ui_url(url, port=port):
                        if url:
                            open_in_default_browser(url)
                        policy = cancel_action
            except Exception:
                logger.exception("navigation policy failed")
                policy = allow_action
            handler(policy)

        def webView_decidePolicyForNavigationResponse_decisionHandler_(  # noqa: N802
            self, webview, navigation_response, handler
        ) -> None:
            policy = allow_response
            try:
                response = navigation_response.response()
                url = ""
                mime = ""
                if response is not None:
                    if response.URL() is not None:
                        url = str(response.URL().absoluteString())
                    mime = str(response.MIMEType() or "")
                disposition = _header(response, "Content-Disposition")
                can_show = True
                try:
                    can_show = bool(navigation_response.canShowMIMEType())
                except Exception:
                    can_show = True
                mime_l = mime.lower()
                page = (
                    mime_l.startswith("text/")
                    or "html" in mime_l
                    or "json" in mime_l
                    or "javascript" in mime_l
                    or mime_l == ""
                )
                if should_download_response(
                    url=url, mime=mime, content_disposition=disposition
                ) or (not can_show and not page):
                    policy = download_response
            except Exception:
                logger.exception("response policy failed")
                policy = allow_response
            handler(policy)

        def webView_navigationAction_didBecomeDownload_(  # noqa: N802
            self, webview, action, download
        ) -> None:
            download.setDelegate_(self)

        def webView_navigationResponse_didBecomeDownload_(  # noqa: N802
            self, webview, navigation_response, download
        ) -> None:
            download.setDelegate_(self)

        def download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(  # noqa: N802
            self, download, response, suggested, completion
        ) -> None:
            try:
                folder = Path.home() / "Downloads"
                folder.mkdir(parents=True, exist_ok=True)
                dest = unique_download_path(folder, str(suggested) if suggested else "")
                logger.info("Saving download to %s", dest)
                completion(Foundation.NSURL.fileURLWithPath_(str(dest)))
            except Exception:
                logger.exception("could not choose a download destination")
                completion(None)

        def download_didFailWithError_resumeData_(self, download, error, _resume) -> None:  # noqa: N802
            logger.warning("Download failed: %s", error)

        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(  # noqa: N802
            self, webview, _config, action, _features
        ):
            url = _action_url(action)
            port = self.controller.port if self.controller is not None else 8080
            if is_local_ui_url(url, port=port):
                request = None
                try:
                    request = action.request()
                except Exception:
                    request = None
                if request is not None:
                    webview.loadRequest_(request)
            elif url:
                open_in_default_browser(url)
            return None

        def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(  # noqa: N802
            self, _webview, message, _frame, handler
        ) -> None:
            self._run_alert(str(message), confirm=False, handler=handler)

        def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(  # noqa: N802
            self, _webview, message, _frame, handler
        ) -> None:
            self._run_alert(str(message), confirm=True, handler=handler)

        def _run_alert(self, message: str, *, confirm: bool, handler) -> None:
            try:
                alert = AppKit.NSAlert.alloc().init()
                alert.setMessageText_("steadyGrind")
                alert.setInformativeText_(message)
                alert.addButtonWithTitle_("OK")
                if confirm:
                    alert.addButtonWithTitle_("Cancel")
                if self.controller is not None and self.controller.window is not None:
                    self.controller.window.makeKeyAndOrderFront_(None)
                AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                code = int(alert.runModal())
            except Exception:
                logger.exception("script dialog failed")
                if confirm:
                    handler(False)
                else:
                    handler()
                return
            if confirm:
                handler(code == first_button)
            else:
                handler()

        def webView_didFailProvisionalNavigation_withError_(  # noqa: N802
            self, webview, _navigation, error
        ) -> None:
            code = 0
            try:
                code = int(error.code())
            except Exception:
                code = 0
            if code == _CANCELLED:
                return
            logger.warning("UI failed to load: %s", error)
            webview.loadHTMLString_baseURL_(_OFFLINE_HTML, None)

    _WebDelegate = WebDelegate
    _delegate_ready = True


def _singleton():
    global _controller
    if not _bind():
        raise RuntimeError("WebKit is not available")
    _install_delegate()
    if _controller is None:
        _controller = _UiController()
    return _controller
