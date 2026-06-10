from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = APP_DIR.parent
VIEWS_DIR = APP_DIR / "views"
TEMPLATES_DIR = VIEWS_DIR / "templates"
STATIC_DIR = VIEWS_DIR / "static"
LOG_DIR = APP_DIR / "log"
RUNTIME_LOG_DIR = LOG_DIR / "runtime"
WORKER_LOG_DIR = LOG_DIR / "workers"
