#!/usr/bin/env python3
"""Локальный HTTP-сервер для папки с расписанием НИКА (info_panel_1.html).

Зачем: страница расписания не работает по file:// (iframe/CORS/шрифты),
ей нужен обычный http://.

Запуск (Windows, из папки со скриптом):
    python serve_lan.py "C:\\raspisanie"
    python serve_lan.py "C:\\raspisanie" -p 8080
    python serve_lan.py "C:\\raspisanie" --open

Скрипт слушает 0.0.0.0 — страница будет доступна другим устройствам в сети
по адресу http://<IP-этого-ПК>:8000/info_panel_1.html
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import socket
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

DEFAULT_FILE = "info_panel_1.html"

# Практически все нужные типы; шрифты и js важны для панели.
EXTRA_TYPES = {
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".eot": "application/vnd.ms-fontobject",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".map": "application/json; charset=utf-8",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler + index-файл по умолчанию + без кеша."""

    default_file = DEFAULT_FILE

    def translate_path(self, path: str) -> str:
        # отрезаем query/fragment
        path = path.split("?", 1)[0].split("#", 1)[0]
        full = super().translate_path(path)
        if os.path.isdir(full):
            candidate = os.path.join(full, self.default_file)
            if os.path.isfile(candidate):
                return candidate
            if self.default_file != "index.html":
                candidate = os.path.join(full, "index.html")
                if os.path.isfile(candidate):
                    return candidate
        return full

    def guess_type(self, path):  # noqa: D102
        ext = Path(path).suffix.lower()
        if ext in EXTRA_TYPES:
            return EXTRA_TYPES[ext]
        return super().guess_type(path)

    def end_headers(self):
        # Панель должна показывать свежее расписание, поэтому кеш выключен.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter, one line per request
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def local_ips() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    # «правильный» адрес узнаём через connect к внешнему адресу (UDP, без трафика)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def main() -> int:
    ap = argparse.ArgumentParser(description="HTTP-сервер для папки расписания")
    ap.add_argument("root", nargs="?", default=".", help="папка с info_panel_1.html")
    ap.add_argument("-p", "--port", type=int, default=8000)
    ap.add_argument("-b", "--bind", default="0.0.0.0", help="интерфейс (по умолчанию все)")
    ap.add_argument("--open", action="store_true", help="открыть страницу в браузере")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"Нет такой папки: {root}", file=sys.stderr)
        return 2
    if not (root / DEFAULT_FILE).is_file():
        print(
            f"Внимание: {DEFAULT_FILE} в папке не найден. "
            f"Будет показан список файлов.",
            file=sys.stderr,
        )

    handler = functools.partial(Handler, directory=str(root))
    try:
        httpd = Server((args.bind, args.port), handler)
    except OSError as exc:
        print(f"Не удалось занять порт {args.port}: {exc}", file=sys.stderr)
        print("Попробуйте другой порт, например -p 8080", file=sys.stderr)
        return 1

    print(f"Каталог: {root}")
    print("Локально:")
    print(f"  http://localhost:{args.port}/{DEFAULT_FILE}")
    ips = local_ips()
    if ips:
        print("По локальной сети:")
        for ip in ips:
            print(f"  http://{ip}:{args.port}/{DEFAULT_FILE}")
    else:
        print("  (IP не определён — проверьте ipconfig)")
    print("Остановить: Ctrl+C")

    if args.open:
        threading.Timer(
            0.7,
            lambda: webbrowser.open(f"http://localhost:{args.port}/{DEFAULT_FILE}"),
        ).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
