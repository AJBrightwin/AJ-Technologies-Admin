"""
AJ Technologies admin dashboard: the page + the JSON API it uses.

Page
    /                               the dashboard (templates/index.html)

API (all JSON; everything except login needs the admin to be signed in)
    POST   /api/login/              sign in             {email, password}
    POST   /api/logout/             sign out
    GET    /api/me/                 who is signed in
    GET    /api/status/             database / storage status for Settings

    GET    /api/enquiries/          list all enquiries
    POST   /api/enquiries/          add an enquiry
    PATCH  /api/enquiries/<id>/     edit (status, notes, details)
    DELETE /api/enquiries/<id>/     delete
    POST   /api/enquiries/bulk/     {ids, action: "status" | "delete", status}

    GET    /api/projects/           list all projects (including hidden)
    POST   /api/projects/           add a project
    PATCH  /api/projects/<id>/      edit (old image is deleted when replaced)
    DELETE /api/projects/<id>/      delete (its image is deleted too)
    POST   /api/projects/reorder/   {ids: [...]} in the new order

    GET    /api/reviews/            list all client reviews (including hidden)
    POST   /api/reviews/            add a review
    PATCH  /api/reviews/<id>/       edit / show / hide
    DELETE /api/reviews/<id>/       delete
    POST   /api/reviews/reorder/    {ids: [...]} in the new order

    GET    /api/images/             images in Storage (project-images/projects/)
    POST   /api/images/             upload (form field "file")
    DELETE /api/images/             {path}
"""
import hmac
import json
import logging
import re
import secrets
import time
from datetime import date, datetime
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, ProgrammingError, connection, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie

from . import storage
from .models import ClientReview, ContactEnquiry, ShowcaseProject

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
@never_cache
@ensure_csrf_cookie
def index(request):
    """The single-page dashboard. All screens live inside templates/index.html."""
    return render(request, 'index.html', {
        'supabase_url': settings.SUPABASE_URL,
        'bucket': settings.SUPABASE_STORAGE_BUCKET,
        'image_folder': settings.SUPABASE_IMAGE_FOLDER,
        'max_image_mb': settings.MAX_IMAGE_MB,
    })


# ---------------------------------------------------------------------------
# API plumbing
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


def ok(status=200, **data):
    return JsonResponse({'ok': True, **data}, status=status)


def _json_body(request):
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ApiError('The request was not valid JSON.')
    if not isinstance(data, dict):
        raise ApiError('The request must be a JSON object.')
    return data


def _is_signed_in(request):
    return request.session.get('admin') is True


def api(methods, login_required=True):
    """Decorator: allowed methods, sign-in check, and friendly JSON errors."""
    def wrap(view):
        @wraps(view)
        @never_cache
        def inner(request, *args, **kwargs):
            if request.method not in methods:
                return JsonResponse({'ok': False, 'error': 'Method not allowed.'}, status=405)
            if login_required and not _is_signed_in(request):
                return JsonResponse({'ok': False, 'error': 'Please sign in again.', 'code': 'auth'}, status=401)
            try:
                return view(request, *args, **kwargs)
            except ApiError as e:
                return JsonResponse({'ok': False, 'error': e.message, **e.extra}, status=e.status)
            except storage.StorageError as e:
                log.warning('Storage: %s', e)
                return JsonResponse({'ok': False, 'error': str(e), 'code': 'storage'}, status=502)
            except DatabaseError:
                log.exception('Database error')
                return JsonResponse({'ok': False, 'error': 'Could not reach the database. Check your internet and DATABASE_URL, then try again.', 'code': 'db'}, status=503)
        return inner
    return wrap


def _get(model, pk):
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist:
        raise ApiError('This item no longer exists. Refresh the page.', 404)


# ---------------------------------------------------------------------------
# Validation (mirrors the CHECK constraints in supabase_schema.sql)
# ---------------------------------------------------------------------------
def _text(v, rule):
    s = str(v if v is not None else '').strip()
    if rule.get('required') and not s:
        raise ValueError('required')
    if len(s) > rule['max']:
        raise ValueError(f'max {rule["max"]} characters')
    return s


def _phone(v, rule):
    s = _text(v, rule)
    if len(re.sub(r'\D', '', s)) < 10:
        raise ValueError('at least 10 digits')
    return s


def _email(v, rule):
    s = _text(v, rule)
    if s:
        try:
            validate_email(s)
        except ValidationError:
            raise ValueError('invalid email')
    return s


def _choice(v, rule):
    s = str(v if v is not None else '').strip()
    if s not in rule['choices']:
        raise ValueError('invalid choice')
    return s


def _list(v, rule):
    if not isinstance(v, list):
        raise ValueError('must be a list')
    out = []
    for item in v:
        s = str(item).strip()
        if s and s not in out:
            if len(s) > rule['item_max']:
                raise ValueError(f'each item max {rule["item_max"]} characters')
            out.append(s)
    if len(out) > rule['max_items']:
        raise ValueError(f'max {rule["max_items"]} items')
    return out


def _bool(v, rule):
    if not isinstance(v, bool):
        raise ValueError('must be true or false')
    return v


def _int(v, rule):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError('must be a whole number')
    if n < 0 or n > 1_000_000:
        raise ValueError('must be 0 or more')
    return n


def _hex(v, rule):
    s = str(v or '').strip().lower()
    if not re.fullmatch(r'#[0-9a-f]{6}', s):
        raise ValueError('must be a colour like #2563eb')
    return s


def _url(v, rule):
    s = _text(v, rule)
    if s and not re.match(r'^https?://\S+\.\S+$', s):
        raise ValueError('must start with http:// or https://')
    return s


def _image_path(v, rule):
    s = _text(v, rule)
    if s and not s.startswith(('http://', 'https://')):
        if '..' in s or s.startswith('/'):
            raise ValueError('invalid image path')
    return s


ENQUIRY_FIELDS = {
    'name':           (_text,   {'max': 120, 'required': True}),
    'phone':          (_phone,  {'max': 30, 'required': True}),
    'email':          (_email,  {'max': 254}),
    'business_name':  (_text,   {'max': 160}),
    'services':       (_list,   {'max_items': 15, 'item_max': 80}),
    'timeline':       (_choice, {'choices': ContactEnquiry.TIMELINES}),
    'contact_method': (_choice, {'choices': ContactEnquiry.CONTACT_METHODS}),
    'message':        (_text,   {'max': 5000}),
    'source':         (_choice, {'choices': ContactEnquiry.SOURCES}),
    'submitted_via':  (_choice, {'choices': ContactEnquiry.VIAS}),
    'language':       (_choice, {'choices': ContactEnquiry.LANGUAGES}),
    'status':         (_choice, {'choices': ContactEnquiry.STATUSES}),
    'notes':          (_text,   {'max': 5000}),
}

PROJECT_FIELDS = {
    'title_en':         (_text,       {'max': 150, 'required': True}),
    'title_ta':         (_text,       {'max': 200}),
    'business_type_en': (_text,       {'max': 150, 'required': True}),
    'business_type_ta': (_text,       {'max': 200}),
    'built_en':         (_text,       {'max': 5000, 'required': True}),
    'built_ta':         (_text,       {'max': 5000}),
    'tags_en':          (_list,       {'max_items': 8, 'item_max': 40}),
    'tags_ta':          (_list,       {'max_items': 8, 'item_max': 40}),
    'category':         (_choice,     {'choices': ShowcaseProject.CATEGORIES}),
    'kind':             (_choice,     {'choices': ShowcaseProject.KINDS}),
    'image_path':       (_image_path, {'max': 500}),
    'color_primary':    (_hex,        {}),
    'color_secondary':  (_hex,        {}),
    'live_url':         (_url,        {'max': 300}),
    'is_sample':        (_bool,       {}),
    'is_published':     (_bool,       {}),
    'show_on_home':     (_bool,       {}),
    'sort_order':       (_int,        {}),
}


def _date(v, rule):
    try:
        d = datetime.strptime(str(v or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('must be a date like 2026-10-28')
    if d > date.today():
        raise ValueError('cannot be in the future')
    return d


def _rating(v, rule):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError('must be 1 to 5')
    if not 1 <= n <= 5:
        raise ValueError('must be 1 to 5')
    return n


def _project_ref(v, rule):
    if v in (None, '', 0, '0'):
        return None
    try:
        pk = int(v)
    except (TypeError, ValueError):
        raise ValueError('invalid project')
    if not ShowcaseProject.objects.filter(pk=pk).exists():
        raise ValueError('project not found')
    return pk


REVIEW_FIELDS = {
    'client_name':   (_text,        {'max': 120, 'required': True}),
    'business_name': (_text,        {'max': 160}),
    'location':      (_text,        {'max': 120}),
    'rating':        (_rating,      {}),
    'review_en':     (_text,        {'max': 2000, 'required': True}),
    'review_ta':     (_text,        {'max': 2000}),
    'project_id':    (_project_ref, {}),
    'source':        (_choice,      {'choices': ClientReview.SOURCES}),
    'review_date':   (_date,        {}),
    'is_published':  (_bool,        {}),
    'sort_order':    (_int,         {}),
}


def _clean(fields, data, partial):
    values, errors = {}, {}
    for key, (convert, rule) in fields.items():
        if key not in data:
            if not partial and rule.get('required'):
                errors[key] = 'required'
            continue
        try:
            values[key] = convert(data[key], rule)
        except ValueError as e:
            errors[key] = str(e)
    if errors:
        raise ApiError('Please fix the highlighted fields.', 400, errors=errors)
    return values


def _save(obj, values):
    for k, v in values.items():
        setattr(obj, k, v)
    obj.save(update_fields=[*values.keys(), 'updated_at'])


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
MAX_LOGIN_FAILS = 5
LOCK_SECONDS = 15 * 60


def _client_ip(request):
    return request.META.get('REMOTE_ADDR', '')


def _user():
    return {'name': settings.ADMIN_NAME, 'email': settings.ADMIN_EMAIL}


@api(['POST'], login_required=False)
def login_view(request):
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        raise ApiError('Admin login is not set up. Add ADMIN_EMAIL and ADMIN_PASSWORD to backend/.env and restart the server.', 503)

    key = f'login-fails:{_client_ip(request)}'
    fails = cache.get(key, 0)
    if fails >= MAX_LOGIN_FAILS:
        raise ApiError('Too many wrong attempts. Please wait 15 minutes and try again.', 429)

    data = _json_body(request)
    email = str(data.get('email', '')).strip().lower()
    password = str(data.get('password', ''))
    good_email = hmac.compare_digest(email.encode(), settings.ADMIN_EMAIL.encode())
    good_pass = hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode())
    if not (good_email and good_pass):
        cache.set(key, fails + 1, LOCK_SECONDS)
        time.sleep(0.6)  # slows down password guessing
        raise ApiError('Wrong email or password.', 401)

    cache.delete(key)
    request.session.cycle_key()
    request.session['admin'] = True
    return ok(user=_user())


@api(['POST'], login_required=False)
def logout_view(request):
    request.session.flush()
    return ok()


@api(['GET'])
def me(request):
    return ok(user=_user())


@api(['GET'])
def status(request):
    with connection.cursor() as cur:
        cur.execute('SELECT 1')
    return ok(
        database={'connected': True, 'host': settings.DATABASES['default'].get('HOST', '')},
        storage={'configured': storage.is_configured(), 'bucket': settings.SUPABASE_STORAGE_BUCKET,
                 'folder': settings.SUPABASE_IMAGE_FOLDER, 'url': settings.SUPABASE_URL},
        counts={'enquiries': ContactEnquiry.objects.count(), 'projects': ShowcaseProject.objects.count()},
    )


# ---------------------------------------------------------------------------
# Enquiries
# ---------------------------------------------------------------------------
@api(['GET', 'POST'])
def enquiries(request):
    if request.method == 'GET':
        return ok(items=[e.to_dict() for e in ContactEnquiry.objects.all()])
    values = _clean(ENQUIRY_FIELDS, _json_body(request), partial=False)
    item = ContactEnquiry.objects.create(**values)
    log.info('Enquiry %s added by admin', item.pk)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
def enquiry_detail(request, pk):
    item = _get(ContactEnquiry, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(ENQUIRY_FIELDS, _json_body(request), partial=True)
    if values:
        _save(item, values)
    return ok(item=item.to_dict())


@api(['POST'])
def enquiries_bulk(request):
    data = _json_body(request)
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > 1000 or not all(isinstance(i, int) for i in ids):
        raise ApiError('Choose at least one enquiry.')
    rows = ContactEnquiry.objects.filter(pk__in=ids)
    action = data.get('action')
    if action == 'status':
        new_status = data.get('status')
        if new_status not in ContactEnquiry.STATUSES:
            raise ApiError('Choose a valid status.')
        count = rows.update(status=new_status, updated_at=timezone.now())
    elif action == 'delete':
        count, _ = rows.delete()
    else:
        raise ApiError('Unknown action.')
    return ok(count=count)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def _delete_image_if_unused(path, except_id=None):
    """Delete an image from Storage when no other project uses it. Returns a warning text or ''."""
    path = (path or '').strip()
    if not path or path.startswith(('http://', 'https://')):
        return ''
    others = ShowcaseProject.objects.filter(image_path=path)
    if except_id is not None:
        others = others.exclude(pk=except_id)
    if others.exists():
        return ''
    try:
        storage.remove([path])
    except storage.StorageError as e:
        log.warning('Could not delete image %s: %s', path, e)
        return f'The project was saved, but the old image could not be deleted from Storage ({e}).'
    return ''


@api(['GET', 'POST'])
def projects(request):
    if request.method == 'GET':
        return ok(items=[p.to_dict() for p in ShowcaseProject.objects.all()])
    values = _clean(PROJECT_FIELDS, _json_body(request), partial=False)
    item = ShowcaseProject.objects.create(**values)
    log.info('Project %s added', item.pk)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
def project_detail(request, pk):
    item = _get(ShowcaseProject, pk)
    if request.method == 'DELETE':
        old_path = item.image_path
        item.delete()
        warning = _delete_image_if_unused(old_path)
        return ok(warning=warning.replace('The project was saved, but the old', 'The project was deleted, but its') if warning else '')

    old_path = item.image_path
    values = _clean(PROJECT_FIELDS, _json_body(request), partial=True)
    if values:
        _save(item, values)
    warning = ''
    if 'image_path' in values and values['image_path'] != old_path:
        warning = _delete_image_if_unused(old_path)
    return ok(item=item.to_dict(), warning=warning)


@api(['POST'])
def projects_reorder(request):
    ids = _json_body(request).get('ids')
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise ApiError('Invalid order.')
    now = timezone.now()
    with transaction.atomic():
        for position, pk in enumerate(ids, start=1):
            ShowcaseProject.objects.filter(pk=pk).update(sort_order=position * 10, updated_at=now)
    return ok(items=[p.to_dict() for p in ShowcaseProject.objects.all()])


# ---------------------------------------------------------------------------
# Client reviews (client_reviews table, created by supabase_reviews.sql)
# ---------------------------------------------------------------------------
NO_REVIEWS_TABLE = ('The reviews table does not exist yet. In Supabase, open SQL Editor and run '
                    'supabase_reviews.sql, then refresh this page.')


def _reviews_table_guard(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ProgrammingError as e:
            if 'client_reviews' in str(e):
                raise ApiError(NO_REVIEWS_TABLE, 503, code='no_table')
            raise
    return inner


@api(['GET', 'POST'])
@_reviews_table_guard
def reviews(request):
    if request.method == 'GET':
        return ok(items=[r.to_dict() for r in ClientReview.objects.all()])
    values = _clean(REVIEW_FIELDS, _json_body(request), partial=False)
    item = ClientReview.objects.create(**values)
    log.info('Review %s added', item.pk)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
@_reviews_table_guard
def review_detail(request, pk):
    item = _get(ClientReview, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(REVIEW_FIELDS, _json_body(request), partial=True)
    if values:
        _save(item, values)
    return ok(item=item.to_dict())


@api(['POST'])
@_reviews_table_guard
def reviews_reorder(request):
    ids = _json_body(request).get('ids')
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise ApiError('Invalid order.')
    now = timezone.now()
    with transaction.atomic():
        for position, pk in enumerate(ids, start=1):
            ClientReview.objects.filter(pk=pk).update(sort_order=position * 10, updated_at=now)
    return ok(items=[r.to_dict() for r in ClientReview.objects.all()])


# ---------------------------------------------------------------------------
# Images (Supabase Storage)
# ---------------------------------------------------------------------------
IMAGE_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}


def _real_image_type(head):
    """Check the file's first bytes, so a renamed non-image file is refused."""
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    return ''


@api(['GET', 'POST', 'DELETE'])
def images(request):
    if request.method == 'GET':
        return ok(items=storage.list_images())

    if request.method == 'POST':
        f = request.FILES.get('file')
        if not f:
            raise ApiError('Choose an image to upload.')
        if f.size > settings.MAX_IMAGE_MB * 1024 * 1024:
            raise ApiError(f'The image is larger than {settings.MAX_IMAGE_MB} MB.')
        content = f.read()
        ctype = _real_image_type(content[:16])
        if ctype not in IMAGE_TYPES:
            raise ApiError('Only JPG, PNG or WebP images can be uploaded.')
        base = re.sub(r'[^a-z0-9]+', '-', f.name.rsplit('.', 1)[0].lower()).strip('-')[:40] or 'image'
        path = f'{settings.SUPABASE_IMAGE_FOLDER}/{date.today().isoformat()}-{base}-{secrets.token_hex(3)}.{IMAGE_TYPES[ctype]}'
        storage.upload(path, content, ctype)
        log.info('Image uploaded: %s', path)
        return ok(201, item={'path': path, 'size': len(content), 'type': ctype,
                             'uploaded_at': timezone.now().isoformat()})

    # DELETE
    data = _json_body(request)
    path = str(data.get('path', '')).strip()
    if not path.startswith(settings.SUPABASE_IMAGE_FOLDER + '/') or '..' in path:
        raise ApiError('Invalid image path.')
    used_by = list(ShowcaseProject.objects.filter(image_path=path).values_list('title_en', flat=True))
    if used_by and not data.get('force'):
        raise ApiError(f'This image is used by: {", ".join(used_by)}.', 409, used_by=used_by)
    storage.remove([path])
    if used_by:
        ShowcaseProject.objects.filter(image_path=path).update(image_path='', updated_at=timezone.now())
    return ok()