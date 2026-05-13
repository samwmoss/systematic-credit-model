"""Shared logging configuration for the pipeline.

Call `setup_logging(config["logging"])` once at startup (from `src/main.py`).
Every other module gets its logger via `logging.getLogger(__name__)`.
"""
import logging
from pathlib import Path


def setup_logging(config: dict) -> None:
    """Configure root logger from the `logging` section of config.yaml.

    Expected config keys:
        level   (str)  — "DEBUG" | "INFO" | "WARNING" | "ERROR"
        file    (str)  — path (relative to cwd) for the log file
        console (bool) — also stream to stderr
        format  (str)  — logging format string
    """
    level    = config.get("level", "INFO").upper()
    file_rel = config.get("file", "logs/pipeline.log")
    console  = config.get("console", True)
    fmt      = config.get("format", "%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    log_path = Path(file_rel)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # Idempotent: clear existing handlers so re-running setup doesn't duplicate output.
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    formatter = logging.Formatter(fmt)

    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setFormatter(formatter)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        root.addHandler(ch)
