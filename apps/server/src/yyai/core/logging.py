"""One logging setup for the server and the worker."""

import logging
import os


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("YYAI_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
