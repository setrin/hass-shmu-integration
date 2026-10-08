"""Supply SHMÚ's missing public intermediate while retaining root verification."""

import ssl
from pathlib import Path

from homeassistant.util.ssl import create_client_context


def observation_ssl_context():
    """Run off the event loop: standard trusted roots plus the public intermediate."""
    context = create_client_context()
    context.load_verify_locations(cafile=str(Path(__file__).parent / "certs/shmu_intermediate.pem"))
    context.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
    return context
