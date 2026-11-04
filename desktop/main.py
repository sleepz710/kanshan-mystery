"""单进程桌面程序，资源只读，所有运行文件写入用户数据目录。"""

import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time


def main():
    directory = Path(os.environ.get("KANSHAN_DATA_DIR") or Path(os.environ.get("APPDATA", Path.home())) / "KanshanMystery")
    directory.mkdir(parents=True, exist_ok=True)
    directory = directory.resolve()
    os.environ.update(KANSHAN_DATA_DIR=str(directory), KANSHAN_DESKTOP="1", LLM_MOCK="0")
    (directory / "logs").mkdir(exist_ok=True)
    logging.basicConfig(filename=directory / "logs" / "desktop.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import msvcrt
    import uvicorn
    import webview
    from webview.menu import Menu, MenuAction

    instance = (directory / "instance.lock").open("a+b")
    instance.seek(0)
    if instance.read(1) == b"":
        instance.write(b"0")
        instance.flush()
    instance.seek(0)
    try:
        msvcrt.locking(instance.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "看山谜案馆已经打开，请回到已有窗口。", "看山谜案馆", 0)
        instance.close()
        return

    from backend.app import app

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, workers=1,
                                         log_config=None, access_log=False, timeout_graceful_shutdown=30))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, name="kanshan-backend")
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            if not worker.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("本地后端未能启动，请查看数据目录中的日志。")
            time.sleep(0.05)
        logging.info("桌面后端就绪 pid=%d port=%d", os.getpid(), port)

        class WindowApi:
            def quit(self):
                window.destroy()

        target = "/" if app.state.desktop_settings.public()["configured"] else "/settings/"
        window = webview.create_window("看山谜案馆", f"http://127.0.0.1:{port}{target}", js_api=WindowApi(),
                                       width=1600, height=900, min_size=(1280, 720), background_color="#101614")
        menu = [Menu("应用", [
            MenuAction("模型设置", lambda: window.load_url(f"http://127.0.0.1:{port}/settings/")),
            MenuAction("返回首页", lambda: window.load_url(f"http://127.0.0.1:{port}/")),
            MenuAction("退出", window.destroy),
        ])]

        def show_native_menu():
            from System import Action
            from System.Windows.Forms import MenuStrip

            def arrange():
                for control in window.native.Controls:
                    if isinstance(control, MenuStrip):
                        window.native.MainMenuStrip = control
                        control.SendToBack()
                window.native.PerformLayout()

            window.native.Invoke(Action(arrange))

        window.events.shown += show_native_menu
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(directory / "webview"),
                      icon=str(Path(__file__).resolve().parent / "kanshan.ico"), menu=menu)
    finally:
        server.should_exit = True
        worker.join()
        listener.close()
        instance.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("桌面启动失败")
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "启动失败。请确认已安装 Edge WebView2 Runtime，并查看用户数据目录中的 logs/desktop.log。", "看山谜案馆", 16)
        raise
