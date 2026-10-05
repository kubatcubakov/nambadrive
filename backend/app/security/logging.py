"""Discard HTTP-client wire/request logs which can contain URL capability secrets."""
import logging


class PrivateTransport(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Do not attempt regex sanitization of arbitrary SDK payloads or exception strings.
        return False


def configure_transport_logging() -> None:
    for name in ("httpx", "httpcore", "botocore", "boto3", "urllib3"):
        logger = logging.getLogger(name)
        logger.addFilter(PrivateTransport())
        logger.propagate = False
        logger.handlers = [logging.NullHandler()]
        # Children inherit no effective output handler; direct child logger filters too.
        for child_name, child in logging.Logger.manager.loggerDict.items():
            if child_name.startswith(name + ".") and isinstance(child, logging.Logger):
                child.addFilter(PrivateTransport())
                child.propagate = False
                child.handlers = [logging.NullHandler()]
