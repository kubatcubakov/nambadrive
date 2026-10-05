"""Scan source for credential patterns without printing matched secrets."""
from pathlib import Path
import re
import sys

patterns = [re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
            re.compile(r'AKIA[A-Z0-9]{16}'), re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}')]
skip = {'.git', '.venv', 'node_modules', 'handoff', 'dist', '__pycache__', '.mypy_cache', '.pytest_cache', '.ruff_cache'}
failed = False
for path in Path('.').rglob('*'):
    if not path.is_file() or set(path.parts) & skip or path.name == 'secret_scan.py':
        continue
    try:
        content = path.read_text()
    except (UnicodeError, OSError):
        continue
    if any(pattern.search(content) for pattern in patterns):
        print(f'Credential pattern detected in {path}')
        failed = True
sys.exit(1 if failed else 0)
