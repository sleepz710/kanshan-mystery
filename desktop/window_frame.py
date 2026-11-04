"""保留 Windows 无边框窗口的缩放、系统拖动和工作区最大化。"""

import ctypes
from ctypes import wintypes

WM_GETMINMAXINFO = 0x0024
WM_NCDESTROY = 0x0082
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


class MinMaxInfo(ctypes.Structure):
    _fields_ = [("reserved", wintypes.POINT), ("max_size", wintypes.POINT),
                ("max_position", wintypes.POINT), ("min_track", wintypes.POINT),
                ("max_track", wintypes.POINT)]


class WindowFrame:
    def __init__(self, native):
        self.native = native
        self.handle = native.Handle.ToInt64()
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
        pointer = ctypes.c_ssize_t
        self.callback_type = ctypes.WINFUNCTYPE(pointer, wintypes.HWND, wintypes.UINT,
                                                wintypes.WPARAM, wintypes.LPARAM,
                                                ctypes.c_size_t, ctypes.c_size_t)
        self.comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, self.callback_type,
                                                   ctypes.c_size_t, ctypes.c_size_t]
        self.comctl32.SetWindowSubclass.restype = wintypes.BOOL
        self.comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, self.callback_type, ctypes.c_size_t]
        self.comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT,
                                                wintypes.WPARAM, wintypes.LPARAM]
        self.comctl32.DefSubclassProc.restype = pointer
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.IsZoomed.argtypes = [wintypes.HWND]
        self.user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user32.MonitorFromWindow.restype = wintypes.HMONITOR
        self.user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        self.user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
        self.user32.SendMessageW.restype = pointer
        self.user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        get_style = self.user32.GetWindowLongPtrW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = pointer
        set_style = self.user32.SetWindowLongPtrW
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, pointer]
        set_style.restype = pointer

        # 回调在窗口整个生命周期内持有，避免原生消息调用已释放的 Python 函数。
        self.callback = self.callback_type(self._window_proc)
        if not self.comctl32.SetWindowSubclass(self.handle, self.callback, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        # 恢复系统缩放和最大/最小化能力，非客户区在 WM_NCCALCSIZE 中消除。
        style = get_style(self.handle, GWL_STYLE) | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
        set_style(self.handle, GWL_STYLE, style)
        self.native.Resize += self._update_padding
        self._update_padding()
        self.user32.SetWindowPos(self.handle, None, 0, 0, 0, 0, 0x0037)

    def is_maximized(self):
        return bool(self.user32.IsZoomed(self.handle))

    def _update_padding(self, sender=None, args=None):
        from System.Windows.Forms import Padding

        # WebView2 填满父窗时会接管边缘命中，留出窄边供系统缩放。
        border = 0 if self.is_maximized() else round(2 * self.user32.GetDpiForWindow(self.handle) / 96)
        if self.native.Padding.All != border:
            self.native.Padding = Padding(border)

    def start_drag(self):
        from System import Action

        def drag():
            self.user32.ReleaseCapture()
            self.user32.SendMessageW(self.handle, WM_NCLBUTTONDOWN, HTCAPTION, 0)

        self.native.Invoke(Action(drag))

    def _window_proc(self, handle, message, wparam, lparam, subclass_id, reference):
        if message == WM_NCCALCSIZE:
            return 0
        if message == WM_NCHITTEST and not self.is_maximized():
            rect = wintypes.RECT()
            self.user32.GetWindowRect(handle, ctypes.byref(rect))
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            border = round(6 * self.user32.GetDpiForWindow(handle) / 96)
            column = 0 if x < rect.left + border else 2 if x >= rect.right - border else 1
            row = 0 if y < rect.top + border else 2 if y >= rect.bottom - border else 1
            hit = ((13, 12, 14), (10, 0, 11), (16, 15, 17))[row][column]
            if hit:
                return hit
        if message == WM_NCDESTROY:
            self.comctl32.RemoveWindowSubclass(handle, self.callback, subclass_id)
        result = self.comctl32.DefSubclassProc(handle, message, wparam, lparam)
        if message == WM_GETMINMAXINFO:
            monitor = self.user32.MonitorFromWindow(handle, 2)
            info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
            if self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                limits = ctypes.cast(lparam, ctypes.POINTER(MinMaxInfo)).contents
                limits.max_position.x = info.work.left - info.monitor.left
                limits.max_position.y = info.work.top - info.monitor.top
                limits.max_size.x = info.work.right - info.work.left
                limits.max_size.y = info.work.bottom - info.work.top
        return result
