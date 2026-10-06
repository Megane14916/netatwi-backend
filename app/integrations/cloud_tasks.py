"""Cloud Tasks request construction and scheduled task creation."""

from datetime import datetime, timedelta, timezone

from flask import current_app, request
from google.auth import exceptions as auth_exceptions
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2


def authenticate_task_request():
    audience = current_app.config.get("TASKS_OIDC_AUDIENCE")
    caller = current_app.config.get("TASKS_SERVICE_ACCOUNT_EMAIL")
    if not audience or not caller:
        return {"error": "Task authentication is not configured"}, 503
    parts = request.headers.get("Authorization", "").split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return {"error": "Task authentication required"}, 401
    try:
        claims = id_token.verify_oauth2_token(parts[1], Request(), audience=audience)
    except auth_exceptions.TransportError:
        current_app.logger.warning("Task token verification unavailable")
        return {"error": "Task authentication unavailable"}, 503
    except (ValueError, auth_exceptions.GoogleAuthError):
        return {"error": "Invalid task token"}, 401
    if claims.get("email_verified") is not True or claims.get("email") != caller:
        return {"error": "Task caller not authorized"}, 403
    return None


def schedule_contest_task(contest_id, event_type, schedule_time):
    project = current_app.config.get("GCP_PROJECT_ID")
    location = current_app.config.get("GCP_LOCATION")
    queue = current_app.config.get("GCP_QUEUE_NAME")
    handler_url = current_app.config.get("TASK_HANDLER_URL") or current_app.config.get("GCR_URL")
    audience = current_app.config.get("TASKS_OIDC_AUDIENCE")
    service_account = current_app.config.get("TASKS_SERVICE_ACCOUNT_EMAIL")

    if not all([project, location, queue, handler_url]):
        print(f"Skipping task scheduling for {event_type} - GCP configuration missing.")
        return

    if not audience or not service_account:
        raise ValueError("Cloud Tasks OIDC audience and service account are required")

    if "cloud_tasks_client" not in current_app.extensions:
        current_app.extensions["cloud_tasks_client"] = tasks_v2.CloudTasksClient()
    client = current_app.extensions["cloud_tasks_client"]
    parent = client.queue_path(project, location, queue)

    url = f"{handler_url}/api/tasks/contest/{contest_id}/{event_type}"

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-type": "application/json"},
            "oidc_token": {"service_account_email": service_account, "audience": audience},
        }
    }

    # 要件: 各イベントの「10秒後」にタスクを実行する（ギリギリの書き込み遅延等を考慮）
    if schedule_time.tzinfo is None:
        schedule_time = schedule_time.replace(tzinfo=timezone.utc)
    schedule_time = schedule_time + timedelta(seconds=10)

    # Ensure schedule time is at least a few seconds in the future
    now = datetime.now(timezone.utc)
    if schedule_time < now:
        schedule_time = now + timedelta(seconds=10)

    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(schedule_time)
    task["schedule_time"] = timestamp

    try:
        response = client.create_task(request={"parent": parent, "task": task})
        print(f"Created task {response.name} for {event_type} at {schedule_time}")
    except Exception as e:
        print(f"Failed to create task for {event_type}: {e}")
