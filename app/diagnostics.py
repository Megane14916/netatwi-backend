"""Safe failure diagnostics without exception messages, data or traceback lines."""

import traceback
from pathlib import Path

from flask import current_app


def log_failure(operation, error, *, logger=None):
    logger = logger if logger is not None else current_app.logger
    frames = traceback.extract_tb(error.__traceback__)
    stack = ' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
                       for frame in frames)
    logger.error('Operation failed; operation=%s; exception_type=%s; stack=%s',
                 operation, type(error).__name__, stack or 'unavailable')
