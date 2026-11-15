"""Start the local calendar once and open its desktop window when requested."""

import argparse
import ctypes
import http.client
import msvcrt
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA = ROOT / ".dailyhelper"
PAGE_TITLE = "<title>我的日程本</title>".encode("utf-8")
PAGE_SCRIPT = b'src="/app.js"'


def calendar_is_running(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.75)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read(4096)
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()
    if response.status == 200 and PAGE_TITLE in page and PAGE_SCRIPT in page:
        return True
    raise RuntimeError(f"端口 {port} 已被另一个程序占用。")


def ensure_service(port):
    if calendar_is_running(port):
        return
    with (DATA / f"launcher-{port}.lock").open("a+b") as lock:
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            if calendar_is_running(port):
                return
            with (DATA / "schedule-server.log").open("ab") as log:
                process = subprocess.Popen(
                    [sys.executable, "-B", str(ROOT / "schedule_app.py"), "--port", str(port)],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if calendar_is_running(port):
                    return
                if process.poll() is not None:
                    break
                time.sleep(0.2)
            raise RuntimeError("日程服务启动失败，请查看 .dailyhelper/schedule-server.log。")
        finally:
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def open_window(port):
    url = f"http://127.0.0.1:{port}"
    relative_edge = Path("Microsoft/Edge/Application/msedge.exe")
    edge = shutil.which("msedge.exe")
    for folder in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(folder)
        if edge is None and base:
            candidate = Path(base) / relative_edge
            if candidate.is_file():
                edge = str(candidate)
    if edge:
        subprocess.Popen([edge, f"--app={url}"], creationflags=subprocess.CREATE_NO_WINDOW)
    elif not webbrowser.open(url):
        raise RuntimeError(f"无法打开日程窗口。可以在浏览器打开 {url}。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", action="store_true", help="Start the service without opening a window")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        DATA.mkdir(exist_ok=True)
        ensure_service(args.port)
        if not args.background:
            open_window(args.port)
    except (OSError, RuntimeError) as error:
        if DATA.is_dir():
            try:
                with (DATA / "launcher.log").open("a", encoding="utf-8") as log:
                    print(time.strftime("%Y-%m-%d %H:%M:%S"), error, file=log)
            except OSError:
                pass
        if not args.background:
            ctypes.windll.user32.MessageBoxW(None, str(error), "我的日程本", 0x10)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
