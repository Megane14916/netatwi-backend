"""Public application exports and canonical backend packages.

Component imports stay independent. The first public runtime export resolves
the default application; direct app.py entries can publish their existing app.
"""

from threading import RLock

_RUNTIME_EXPORTS = (
    'BLUEPRINTS',
    'Bookmark',
    'Comment',
    'Contest',
    'ContestResult',
    'IntegrityError',
    'JST',
    'Notification',
    'Post',
    'User',
    'Vote',
    '_register_extracted_routes',
    'app',
    'backend_url',
    'cloud_tasks',
    'create_app',
    'create_base_app',
    'datetime',
    'db',
    'frontend_url',
    'get_current_user',
    'handle_contest_task',
    'image_storage',
    'index',
    'initialize_application',
    'is_local_dev',
    'joinedload',
    'jsonify',
    'logger',
    'logging',
    'logout',
    'migrate',
    'os',
    'process_contests_command',
    're',
    'redirect',
    'register_cli',
    'request',
    'results_service',
    'runtime_settings',
    'session',
    'timedelta',
    'timezone',
    'traceback',
    'update_user_stats',
    'url_for',
    'withdraw_user',
)

_RUNTIME_LOCK = RLock()
_RUNTIME_READY = False


def _publish_entry(namespace):
    global _RUNTIME_READY
    with _RUNTIME_LOCK:
        if not _RUNTIME_READY:
            globals().update({name: namespace[name] for name in _RUNTIME_EXPORTS})
            _RUNTIME_READY = True


def __getattr__(name):
    global _RUNTIME_READY
    if name not in _RUNTIME_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    with _RUNTIME_LOCK:
        if not _RUNTIME_READY:
            before = {key: globals()[key] for key in _RUNTIME_EXPORTS if key in globals()}
            try:
                from .factory import initialize_application

                globals()["initialize_application"] = initialize_application
                initialize_application(globals())
            except BaseException:
                for key in _RUNTIME_EXPORTS:
                    if key in before:
                        globals()[key] = before[key]
                    else:
                        globals().pop(key, None)
                raise
            _RUNTIME_READY = True
    return globals()[name]


def __dir__():
    return sorted(set(globals()) | set(_RUNTIME_EXPORTS))
