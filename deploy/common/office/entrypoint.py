"""Private local configuration only; never output secret values."""
import json
import os
import re
import shutil
import stat
from pathlib import Path

source = Path('/run/private/office-local.json')
info = source.lstat()
if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 65536:
    raise SystemExit('Private Office configuration required')
config = json.loads(source.read_text())
service = config['services']['CoAuthoring']
browser, inbox, outbox = [service['secret'][name]['string'] for name in ('browser', 'inbox', 'outbox')]
if browser != inbox or browser == outbox or not all(re.fullmatch(r'[A-Za-z0-9_-]{32,}', value) for value in (browser, outbox)):
    raise SystemExit('Distinct valid browser/inbox and outbox keys required')
if service['token']['enable'] != {'browser': True, 'request': {'inbox': True, 'outbox': True}}:
    raise SystemExit('All Office JWT checks must remain enabled')
shutil.copyfile(source, '/etc/onlyoffice/documentserver/local.json')
os.chmod('/etc/onlyoffice/documentserver/local.json', 0o600)
os.environ.update(JWT_ENABLED='true', JWT_SECRET=browser, JWT_OUTBOX_SECRET=outbox,
                  JWT_HEADER='Authorization', JWT_IN_BODY='false')
os.execv('/app/ds/run-document-server.sh', ['/app/ds/run-document-server.sh'])
