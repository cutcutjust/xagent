"""Structured logging via loguru."""
import sys

from loguru import logger

from app.core.config import get_settings


def setup_logger() -> None:
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
        colorize=True,
    )
    log_dir = settings.data_path / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "sightops_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="1 day",
        retention="14 days",
        serialize=False,
    )


setup_logger()

__all__ = ["logger"]
