"""Start a private Excel instance via COM and always shut down exactly that instance.

Only the process whose PID belongs to the Excel window we created is ever terminated;
Excel windows the user has open are untouched.
"""

from __future__ import annotations

import contextlib
import time
import winreg

ACCESS_VBOM_KEY = r"Software\Microsoft\Office\16.0\Excel\Security"


def access_vbom_enabled() -> bool:
    """Read-only check of 'Trust access to the VBA project object model'."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ACCESS_VBOM_KEY) as k:
            val, _ = winreg.QueryValueEx(k, "AccessVBOM")
            return int(val) == 1
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    import win32api
    import win32con
    try:
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return False
    try:
        import win32process
        return win32process.GetExitCodeProcess(h) == 259  # STILL_ACTIVE
    finally:
        win32api.CloseHandle(h)


@contextlib.contextmanager
def excel_app():
    import pythoncom
    import win32com.client
    import win32process

    pythoncom.CoInitialize()
    app = win32com.client.DispatchEx("Excel.Application")  # always a NEW instance
    _, pid = win32process.GetWindowThreadProcessId(app.Hwnd)
    print(f"[excel_session] started private Excel instance pid={pid}")
    app.Visible = False
    app.DisplayAlerts = False
    try:
        yield app, pid
    finally:
        try:
            for wb in list(app.Workbooks):
                wb.Close(SaveChanges=False)
        except Exception:
            pass
        try:
            app.Quit()
        except Exception:
            pass
        del app
        pythoncom.CoUninitialize()
        for _ in range(50):
            if not _pid_alive(pid):
                break
            time.sleep(0.2)
        if _pid_alive(pid):
            import win32api
            import win32con
            h = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
            win32api.TerminateProcess(h, 1)
            win32api.CloseHandle(h)
            print(f"[excel_session] pid={pid} did not quit; terminated that pid only")
        else:
            print(f"[excel_session] pid={pid} exited")
