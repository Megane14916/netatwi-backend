"""Read-only report of legacy images and duplicate references (Refs #71)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import Post


def audit_images():
    posts = Post.query.filter(Post.image_urls.isnot(None)).all()
    references = {}
    for post in posts:
        if isinstance(post.images, list):
            for url in post.images:
                if isinstance(url, str):
                    references.setdefault(url, set()).add(post.id)
    report = []
    for post in posts:
        images = post.images
        if not isinstance(images, list):
            report.append({"post_id": post.id, "invalid_image_list": True})
            continue
        unverified = [url for url in images if url not in post.owned_images]
        shared = {url: sorted(references[url]) for url in images
                  if isinstance(url, str) and len(references[url]) > 1}
        if unverified or shared:
            report.append({"post_id": post.id, "unverified": unverified, "shared": shared})
    return report


if __name__ == "__main__":
    with create_app().app_context():
        print(json.dumps(audit_images(), ensure_ascii=False, indent=2))
