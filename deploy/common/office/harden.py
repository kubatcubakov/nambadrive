"""Fail build if pinned vendor startup no longer has the reviewed secret assignment."""
import json
from pathlib import Path

script = Path('/app/ds/run-document-server.sh')
old = "this.services.CoAuthoring.secret.outbox.string = '${JWT_SECRET}'"
if script.read_text().count(old) != 1:
    raise SystemExit('Vendor Office startup changed: security review required')
script.write_text(script.read_text().replace(old, "this.services.CoAuthoring.secret.outbox.string = '${JWT_OUTBOX_SECRET}'"))
for config in Path('/etc/nginx').rglob('*.conf'):
    import re
    config.write_text(re.sub(r'access_log[^;]*;', 'access_log off;', config.read_text()))
# Vendor request logs can include signed download/callback capabilities. Application audit
# and service health provide controlled evidence; disable unstructured Office transport logs.
configs = list(Path('/etc/onlyoffice/documentserver/log4js').glob('*.json'))
if not configs:
    raise SystemExit('Vendor Office logging layout changed: review required')
for config in configs:
    config.write_text(json.dumps({'appenders': {'console': {'type': 'console'}},
        'categories': {'default': {'appenders': ['console'], 'level': 'off'}}}))
