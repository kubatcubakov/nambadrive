import io
import os

import pytest

from app.documents.antivirus import ClamAV

pytestmark = pytest.mark.skipif(
    os.environ.get("NAMBADRIVE_TEST_CLAMAV") != "1", reason="Isolated ClamAV not configured"
)


def test_real_clamav_clean_and_eicar():
    scanner = ClamAV(
        "127.0.0.1", int(os.environ.get("NAMBADRIVE_TEST_CLAMAV_PORT", "13310")), 524288000
    )
    assert scanner.scan(io.BytesIO(b"Hello NambaDrive"))
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    assert not scanner.scan(io.BytesIO(eicar))
