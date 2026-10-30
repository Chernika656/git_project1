"""Пути ресурсов относительно репозитория, независимо от рабочей директории."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / 'frontend'
EXAMPLES_DIR = PROJECT_ROOT / 'examples'
REPORT_STYLE = PROJECT_ROOT / 'resources' / 'report.css'
ENV_FILE = PROJECT_ROOT / '.env'
