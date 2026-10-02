import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_PATH = Path("data") / "logs" / "keepmeet.log"
_configured = False


def setup_logging():
    global _configured
    if _configured:
        return
    _configured = True
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("keepmeet")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
