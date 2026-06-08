"""
backup_upload management command
=================================
Uploads a backup file to an S3-compatible storage bucket.

This command is OPTIONAL and requires:
  - boto3 installed: pip install boto3
  - AWS_S3_BUCKET_NAME set in environment

Environment variables:
  AWS_S3_BUCKET_NAME      — required for upload (e.g. my-erp-backups)
  AWS_ACCESS_KEY_ID       — AWS/compatible credentials
  AWS_SECRET_ACCESS_KEY   — AWS/compatible credentials
  AWS_S3_ENDPOINT_URL     — for S3-compatible services (Cloudflare R2, MinIO, etc.)
  AWS_S3_REGION           — region (default: us-east-1)
  AWS_S3_PREFIX           — folder prefix inside bucket (default: backups/)

Usage:
  python manage.py backup_upload backups/backup_sqlite_20240101_020000.sqlite3.enc
  python manage.py backup_upload backups/backup_sqlite_20240101_020000.sqlite3.enc --prefix archive/2024/
"""
import os
import sys
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Upload a backup file to S3-compatible remote storage. '
        'Requires AWS_S3_BUCKET_NAME environment variable and boto3 installed. '
        'Silently skips if bucket is not configured.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'file',
            type=str,
            help='Path to the backup file to upload (absolute or relative to BASE_DIR).',
        )
        parser.add_argument(
            '--prefix',
            type=str,
            default=None,
            help='S3 key prefix/folder (overrides AWS_S3_PREFIX env var).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be uploaded without actually uploading.',
        )

    def handle(self, *args, **options):
        bucket = os.environ.get('AWS_S3_BUCKET_NAME', '').strip()
        if not bucket:
            self.stdout.write(self.style.WARNING(
                'AWS_S3_BUCKET_NAME is not set — remote upload skipped. '
                'Set it to enable off-site backup storage.'
            ))
            return  # Exit 0: intentionally no-op

        # Resolve file path
        from django.conf import settings
        file_path = Path(options['file'])
        if not file_path.is_absolute():
            file_path = Path(settings.BASE_DIR) / file_path

        if not file_path.exists():
            self.stderr.write(self.style.ERROR(f'File not found: {file_path}'))
            sys.exit(1)

        # Determine S3 key
        prefix = options['prefix'] or os.environ.get('AWS_S3_PREFIX', 'backups/').rstrip('/') + '/'
        s3_key = f'{prefix}{file_path.name}'

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[DRY RUN] Would upload {file_path} → s3://{bucket}/{s3_key}'
            ))
            return

        # Import boto3 lazily so missing library doesn't break the app
        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError:
            self.stderr.write(self.style.ERROR(
                'boto3 is not installed. Install it with: pip install boto3'
            ))
            sys.exit(1)

        # Build boto3 client — credentials come from env or IAM role automatically
        endpoint_url = os.environ.get('AWS_S3_ENDPOINT_URL', '').strip() or None
        region = os.environ.get('AWS_S3_REGION', 'us-east-1').strip()

        try:
            client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                region_name=region,
            )
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Failed to create S3 client: {exc}'))
            sys.exit(1)

        file_size = file_path.stat().st_size
        self.stdout.write(
            f'Uploading {file_path.name} ({file_size:,} bytes) → s3://{bucket}/{s3_key} ...'
        )

        try:
            client.upload_file(
                str(file_path),
                bucket,
                s3_key,
                ExtraArgs={
                    'ServerSideEncryption': 'AES256',
                },
            )
            self.stdout.write(self.style.SUCCESS(
                f'Upload complete: s3://{bucket}/{s3_key}'
            ))
        except (BotoCoreError, ClientError) as exc:
            self.stderr.write(self.style.ERROR(f'Upload failed: {exc}'))
            sys.exit(1)
        except OSError as exc:
            self.stderr.write(self.style.ERROR(f'File read error during upload: {exc}'))
            sys.exit(1)
