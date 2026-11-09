"""
WSGI-вход для хостингов без ASGI (PythonAnywhere и т.п.): FastAPI (ASGI)
оборачивается в WSGI через a2wsgi. uWSGI/gunicorn+uvicorn-worker не нужны.
"""
import os
import sys
from pathlib import Path

# чтобы `import app` находил backend/ независимо от cwd воркера
sys.path.insert(0, str(Path(__file__).resolve().parent))

# дефолты (на PythonAnywhere задаются в главном wsgi-файле ПЕРЕД import wsgi)
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("BACKUP_GH_REPO", "allexme8-create/new-raspisanie")

from a2wsgi import ASGIMiddleware  # noqa: E402

from app import app  # noqa: E402

application = ASGIMiddleware(app)
