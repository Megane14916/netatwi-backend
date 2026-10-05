"""Cloud Tasks request construction and scheduled task creation."""

import os
from datetime import datetime, timedelta, timezone

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2


_cloud_tasks_client = None


def schedule_contest_task(contest_id, event_type, schedule_time):
    global _cloud_tasks_client
    project = os.environ.get("GCP_PROJECT_ID")
    location = os.environ.get("GCP_LOCATION")
    queue = os.environ.get("GCP_QUEUE_NAME")
    handler_url = os.environ.get("TASK_HANDLER_URL") or os.environ.get("GCR_URL")

    if not all([project, location, queue, handler_url]):
        print(f"Skipping task scheduling for {event_type} - GCP configuration missing.")
        return

    if _cloud_tasks_client is None:
        _cloud_tasks_client = tasks_v2.CloudTasksClient()
    client = _cloud_tasks_client
    parent = client.queue_path(project, location, queue)

    url = f"{handler_url}/api/tasks/contest/{contest_id}/{event_type}"

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-type": "application/json"},
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
