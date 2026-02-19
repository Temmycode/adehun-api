import logging
from enum import StrEnum

LOG_FORMAT_DEBUG = "%(levelname)s:%(message)s:%(pathname)s:%(funcName)s:%(lineno)d"


class LogLevels(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def configure_logging(log_level: str = LogLevels.ERROR):
    level = str(log_level).upper()

    if level not in logging._nameToLevel:
        level = LogLevels.ERROR

    if level == LogLevels.DEBUG:
        logging.basicConfig(
            level=logging.DEBUG,
            format=LOG_FORMAT_DEBUG,
        )
    else:
        logging.basicConfig(level=logging._nameToLevel[level])


def silence_third_party_loggers():
    logging.getLogger("python_multipart").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("stripe").setLevel(logging.INFO)  # or WARNING
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
