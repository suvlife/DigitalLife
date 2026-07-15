"""Windows 启动器：启动后端服务并打开浏览器。

打包为 zip 便携版后作为可执行入口。前台运行后端；启动后延迟打开
默认浏览器指向本地 Web 界面。Ctrl+C 或关闭窗口即退出。
"""
import asyncio
import os
import sys
import threading
import time
import webbrowser

import backend_main
from util import configUtil


def _open_browser_when_ready(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    time.sleep(2.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"\n数字人生已启动，请在浏览器打开： {url}\n（按 Ctrl+C 退出）\n", flush=True)


def main() -> None:
    app_config = configUtil.load()
    port = app_config.setting.bind_port

    if os.environ.get("DIGITALLIFE_NO_BROWSER") != "1":
        threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(backend_main.main(port=port))
    except KeyboardInterrupt:
        print("\n正在退出……", flush=True)
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
