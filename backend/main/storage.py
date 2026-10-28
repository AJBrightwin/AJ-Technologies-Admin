"""
Supabase Storage helper: upload, list and delete project images.

Uses the Storage REST API with the SECRET key (SUPABASE_SERVICE_KEY in .env).
This key runs only on the server; it is never sent to the browser.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class StorageError(Exception):
    """Raised when Supabase Storage is not set up or returns an error."""


def is_configured():
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY)


def _request(method, url_path, data=None, content_type=None, extra_headers=None, timeout=30):
    if not is_configured():
        raise StorageError('Image storage is not set up. Add SUPABASE_URL and SUPABASE_SERVICE_KEY to backend/.env and restart.')

    key = settings.SUPABASE_SERVICE_KEY
    headers = {'apikey': key}
    if key.startswith('eyJ'):                     # older "service_role" JWT key
        headers['Authorization'] = f'Bearer {key}'
    if content_type:
        headers['Content-Type'] = content_type
    headers.update(extra_headers or {})

    url = f'{settings.SUPABASE_URL}/storage/v1/{url_path}'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:300]
        raise StorageError(f'Supabase Storage error {e.code}: {detail}') from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise StorageError(f'Could not reach Supabase Storage: {getattr(e, "reason", e)}') from e
    return json.loads(raw) if raw else None


def _bucket():
    return urllib.parse.quote(settings.SUPABASE_STORAGE_BUCKET)


def upload(path, content, content_type):
    """Upload bytes to <bucket>/<path>. Fails if the file already exists."""
    _request(
        'POST', f'object/{_bucket()}/{urllib.parse.quote(path)}',
        data=content, content_type=content_type,
        extra_headers={'x-upsert': 'false', 'cache-control': 'max-age=3600'},
    )


def remove(paths):
    """Delete one or more files from the bucket."""
    paths = [p for p in paths if p]
    if paths:
        _request('DELETE', f'object/{_bucket()}', data=json.dumps({'prefixes': paths}).encode(),
                 content_type='application/json')


def list_images():
    """All files in the projects/ folder, newest first."""
    folder = settings.SUPABASE_IMAGE_FOLDER
    rows = _request(
        'POST', f'object/list/{_bucket()}',
        data=json.dumps({'prefix': folder, 'limit': 1000, 'offset': 0,
                         'sortBy': {'column': 'created_at', 'order': 'desc'}}).encode(),
        content_type='application/json',
    ) or []
    images = []
    for row in rows:
        name = row.get('name') or ''
        if not row.get('id') or name.startswith('.'):     # skip sub-folders and placeholder files
            continue
        meta = row.get('metadata') or {}
        images.append({
            'path': f'{folder}/{name}',
            'size': meta.get('size') or 0,
            'type': meta.get('mimetype') or '',
            'uploaded_at': row.get('created_at') or '',
        })
    return images