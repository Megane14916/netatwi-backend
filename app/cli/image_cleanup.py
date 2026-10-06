"""Retry only server-signed cleanup requests after checking current references."""

import click
from flask.cli import with_appcontext
from itsdangerous import BadSignature

from app.services.posts import retry_image_cleanup


@click.command("retry-image-cleanup")
@click.option("--token", required=True, help="Token from IMAGE_CLEANUP_PENDING logs.")
@with_appcontext
def retry_image_cleanup_command(token):
    try:
        completed = retry_image_cleanup(token)
    except (BadSignature, ValueError) as error:
        raise click.ClickException("Invalid cleanup token") from error
    if not completed:
        raise click.ClickException("Cleanup pending: storage unavailable or image referenced")
    click.echo("Image cleanup completed")
