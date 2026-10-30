"""Only OS session/power lifecycle, never application introspection."""

import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Slot


class SleepSignals(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self.sleeping = False
        self.locked = False

    def apply(self):
        if self.widget.kernel:
            self.widget.kernel.suspend() if self.sleeping or self.locked else self.widget.kernel.resume()

    @Slot(bool)
    def sleep(self, sleeping):
        self.sleeping = sleeping
        self.apply()

    @Slot()
    def lock(self):
        self.locked = True
        self.apply()

    @Slot()
    def unlock(self):
        self.locked = False
        self.apply()


class SessionLifecycle(QAbstractNativeEventFilter):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.signals = SleepSignals(widget)
        self._wts = False
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.wtsapi32.WTSRegisterSessionNotification.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self._wts = bool(ctypes.windll.wtsapi32.WTSRegisterSessionNotification(int(widget.winId()), 0))
        elif sys.platform.startswith("linux"):
            self._connect_linux()

    def _connect_linux(self):
        import os
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
        bus = QDBusConnection.systemBus()
        bus.connect("org.freedesktop.login1", "/org/freedesktop/login1",
                    "org.freedesktop.login1.Manager", "PrepareForSleep", self.signals, "sleep(bool)")
        session_id = os.environ.get("XDG_SESSION_ID", "")
        if session_id:
            manager = QDBusInterface("org.freedesktop.login1", "/org/freedesktop/login1",
                                     "org.freedesktop.login1.Manager", bus)
            reply = manager.call("GetSession", session_id)
            if reply.arguments():
                value = reply.arguments()[0]
                path = value.path() if hasattr(value, "path") else str(value)
                bus.connect("org.freedesktop.login1", path, "org.freedesktop.login1.Session",
                            "Lock", self.signals, "lock()")
                bus.connect("org.freedesktop.login1", path, "org.freedesktop.login1.Session",
                            "Unlock", self.signals, "unlock()")

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0
        import ctypes
        from ctypes.wintypes import MSG
        msg = MSG.from_address(int(message))
        if msg.message == 0x218:  # WM_POWERBROADCAST
            if msg.wParam == 4:
                self.signals.sleep(True)
            elif msg.wParam in (7, 18):
                self.signals.sleep(False)
        elif msg.message == 0x2B1:  # WM_WTSSESSION_CHANGE
            if msg.wParam == 7:
                self.signals.lock()
            elif msg.wParam == 8:
                self.signals.unlock()
        elif msg.message == 0x11:  # WM_QUERYENDSESSION
            self.widget.shutdown()
        return False, 0

    def close(self):
        if self._wts:
            import ctypes
            ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification.argtypes = [ctypes.c_void_p]
            ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(int(self.widget.winId()))
