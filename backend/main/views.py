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

    WhatsApp (tables from supabase_whatsapp.sql, filled by the WhatsApp bot)
    GET    /api/wa/chats/                       all chats (newest first)
    GET    /api/wa/chats/<wa_id>/               one chat: messages (?before=<id> older, ?after=<id> newer)
    PATCH  /api/wa/chats/<wa_id>/               {bot_enabled, needs_reply, name}
    DELETE /api/wa/chats/<wa_id>/               delete the chat and its messages
    POST   /api/wa/chats/<wa_id>/read/          mark as read
    POST   /api/wa/chats/<wa_id>/send/          {text} your reply (inside the 24-hour window)
    POST   /api/wa/chats/<wa_id>/review/        ask the customer for a review
    POST   /api/wa/templates/send/              {phone, template, language, params, header_image, body}
    GET    /api/wa/templates/                   approved templates from Meta
    GET    /api/wa/media/<media_id>/            a customer's photo / voice note / file
    GET    /api/wa/bookings/                    calls booked through the bot
    PATCH  /api/wa/bookings/<id>/               {status, notes}
    GET    /api/wa/broadcasts/                  offer broadcasts
    POST   /api/wa/broadcasts/                  queue a broadcast (the bot sends it)
    POST   /api/wa/broadcasts/<id>/cancel/      stop a broadcast

    Upgrade v2 (tables from supabase_upgrade_v2.sql)
    GET/POST          /api/clients/projects/              client projects
    PATCH/DELETE      /api/clients/projects/<id>/
    POST              /api/clients/projects/<id>/notify/  send the project update to the client
    GET/POST          /api/clients/renewals/              domain / hosting / AMC renewals
    PATCH/DELETE      /api/clients/renewals/<id>/
    GET               /api/clients/tickets/               support requests
    PATCH             /api/clients/tickets/<id>/          {status, client_update, private_notes, notify}
    GET/POST          /api/knowledge/                     bot FAQs (+ unanswered questions)
    PATCH/DELETE      /api/knowledge/<id>/
    PATCH             /api/knowledge/unanswered/<id>/     {status: ignored}
    GET               /api/reports/?days=7                numbers for the Reports tab
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
from django.db import DatabaseError, IntegrityError, ProgrammingError, connection, transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie

from . import storage, whatsapp
from .models import (BotKnowledge, BotUnanswered, ClientProject, ClientRenewal, ClientReview, ContactEnquiry,
                     ShowcaseProject, SupportTicket, WaBooking, WaBroadcast, WaBroadcastRecipient, WaContact, WaMessage)

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
            except whatsapp.WhatsAppError as e:
                log.warning('WhatsApp: %s', e)
                return JsonResponse({'ok': False, 'error': str(e), 'code': 'whatsapp'}, status=502)
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
        whatsapp={'configured': whatsapp.is_configured(), 'templates': bool(settings.WABA_ID),
                  'review_template': settings.REVIEW_TEMPLATE_NAME, 'admin_number': settings.ADMIN_WA_NUMBER},
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



# ---------------------------------------------------------------------------
# WhatsApp (chats with the bot, your replies, calls, broadcasts)
# ---------------------------------------------------------------------------
NO_WA_TABLES = ('The WhatsApp tables do not exist yet. In Supabase, open SQL Editor and run supabase_whatsapp.sql '
                '(from the WhatsApp bot project), then refresh this page.')


def _wa_guard(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ProgrammingError as e:
            if 'wa_' in str(e):
                raise ApiError(NO_WA_TABLES, 503, code='no_table')
            raise
    return inner


def _wa_number(value):
    d = re.sub(r'\D', '', str(value or ''))
    if len(d) == 10:
        d = '91' + d
    if len(d) == 11 and d.startswith('0'):
        d = '91' + d[1:]
    if not 10 <= len(d) <= 15:
        raise ApiError('Enter a valid WhatsApp number with country code, e.g. +91 98765 43210.', 400,
                       errors={'phone': 'invalid'})
    return d


def _chat(wa_id):
    try:
        return WaContact.objects.get(pk=wa_id)
    except WaContact.DoesNotExist:
        raise ApiError('This chat no longer exists. Refresh the page.', 404)


def _record_out(contact, sender, msg_type, body, wamid, clear=True):
    now = timezone.now()
    fields = dict(wa_id=contact.wa_id, direction='out', sender=sender, msg_type=msg_type, body=body,
                  status='sent', created_at=now)
    try:
        with transaction.atomic():
            msg = WaMessage.objects.create(wamid=wamid, **fields)
    except IntegrityError:                      # already saved (the message was sent, so never fail here)
        msg = WaMessage.objects.create(wamid=None, **fields)
    extra = {'needs_reply': False, 'unread_count': 0} if clear else {}
    WaContact.objects.filter(pk=contact.wa_id).update(
        last_outbound_at=now, last_message_at=now, last_message_preview=' '.join(body.split())[:200],
        updated_at=now, **extra)
    contact.refresh_from_db()
    return msg


def _phone_enquiries(wa_id):
    with connection.cursor() as cur:
        cur.execute("""SELECT id, status, created_at, services FROM contact_enquiries
                       WHERE right(regexp_replace(phone, '\\D', '', 'g'), 10) = %s
                       ORDER BY created_at DESC LIMIT 10""", [wa_id[-10:]])
        return [{'id': r[0], 'status': r[1], 'created_at': r[2].isoformat(),
                 'services': r[3] if isinstance(r[3], list) else json.loads(r[3] or '[]')} for r in cur.fetchall()]


@api(['GET'])
@_wa_guard
def wa_chats(request):
    now = timezone.now()
    rows = WaContact.objects.order_by(F('last_message_at').desc(nulls_last=True))[:500]
    return ok(items=[c.to_dict(now) for c in rows], configured=whatsapp.is_configured(),
              admin=settings.ADMIN_WA_NUMBER, review_template=settings.REVIEW_TEMPLATE_NAME)


@api(['GET', 'PATCH', 'DELETE'])
@_wa_guard
def wa_chat(request, wa_id):
    contact = _chat(wa_id)
    now = timezone.now()
    if request.method == 'DELETE':
        contact.delete()
        return ok()
    if request.method == 'PATCH':
        data = _json_body(request)
        values = {}
        for key in ('bot_enabled', 'needs_reply'):
            if key in data:
                if not isinstance(data[key], bool):
                    raise ApiError('Invalid value.')
                values[key] = data[key]
        if 'name' in data:
            values['name'] = _text(data['name'], {'max': 120}) if len(str(data['name'] or '')) <= 120 else None
            if values['name'] is None:
                raise ApiError('Name is too long (max 120 characters).', errors={'name': 'max 120 characters'})
        if values:
            WaContact.objects.filter(pk=wa_id).update(**values, updated_at=now)
            contact.refresh_from_db()
        return ok(contact=contact.to_dict(now))

    msgs = WaMessage.objects.filter(wa_id=wa_id)
    after, before = request.GET.get('after'), request.GET.get('before')
    if after and after.isdigit():
        items, has_more = list(msgs.filter(id__gt=int(after)).order_by('id')[:300]), None
    else:
        if before and before.isdigit():
            msgs = msgs.filter(id__lt=int(before))
        items = list(msgs.order_by('-id')[:80])
        has_more = len(items) == 80
        items.reverse()
    extra = {}
    if not after:
        extra = {'enquiries': _phone_enquiries(wa_id),
                 'bookings': [b.to_dict() for b in WaBooking.objects.filter(wa_id=wa_id)[:10]]}
    return ok(contact=contact.to_dict(now), messages=[m.to_dict() for m in items], has_more=has_more, **extra)


@api(['POST'])
@_wa_guard
def wa_read(request, wa_id):
    WaContact.objects.filter(pk=wa_id).update(unread_count=0)
    return ok()


@api(['POST'])
@_wa_guard
def wa_send(request, wa_id):
    contact = _chat(wa_id)
    text = str(_json_body(request).get('text') or '').strip()
    if not text:
        raise ApiError('Type a message first.')
    if len(text) > 4096:
        raise ApiError('The message is too long (max 4096 characters).')
    now = timezone.now()
    if not contact.window_open(now):
        raise ApiError('More than 24 hours have passed since this customer last messaged, so WhatsApp only allows '
                       'an approved template. Use "Send template".', 409, code='window')
    wamid = whatsapp.send(contact.wa_id, whatsapp.text_payload(text))
    msg = _record_out(contact, 'admin', 'text', text, wamid)
    return ok(message=msg.to_dict(), contact=contact.to_dict(now))


TEMPLATE_NAME_RE = re.compile(r'^[a-z0-9_]{1,512}$')
LANG_CODE_RE = re.compile(r'^[A-Za-z]{2,3}(_[A-Za-z]{2,4})?$')


def _template_values(data):
    name = str(data.get('template') or '').strip()
    language = str(data.get('language') or '').strip()
    if not TEMPLATE_NAME_RE.match(name):
        raise ApiError('Choose a template.', errors={'template': 'required'})
    if not LANG_CODE_RE.match(language):
        raise ApiError('Invalid template language.')
    params = data.get('params') or []
    if not isinstance(params, list) or len(params) > 20:
        raise ApiError('Invalid template values.')
    params = [str(p if p is not None else '').strip() for p in params]
    missing = [i + 1 for i, p in enumerate(params) if not p]
    if missing:
        raise ApiError('Fill in every template value: ' + ', '.join('{{%d}}' % n for n in missing) + '.',
                       errors={f'p{n}': 'required' for n in missing})
    if any(len(p) > 300 for p in params):
        raise ApiError('Each template value can be up to 300 characters.')
    header_image = str(data.get('header_image') or '').strip()
    if header_image and not re.match(r'^https://\S+\.\S+$', header_image):
        raise ApiError('The header image must be an https:// link to a JPG or PNG.', errors={'header_image': 'invalid'})
    body = str(data.get('body') or '')[:2000]
    return name, language, params, header_image, body


def _render(body, params):
    for i, p in enumerate(params, start=1):
        body = re.sub(r'\{\{\s*%d\s*\}\}' % i, p, body)
    return body


@api(['POST'])
@_wa_guard
def wa_send_template(request):
    data = _json_body(request)
    wa_id = _wa_number(data.get('phone') or data.get('wa_id'))
    name, language, params, header_image, body = _template_values(data)
    if wa_id == settings.ADMIN_WA_NUMBER:
        raise ApiError('That is your own alerts number. Use a customer number.', errors={'phone': 'own number'})
    contact, _ = WaContact.objects.get_or_create(pk=wa_id)
    customer = (contact.name or contact.profile_name or '').split(' ')[0] or ('நண்பரே' if language.startswith('ta') else 'there')
    params = [p.replace('{name}', customer) for p in params]
    payloads = ['rv:start'] if name == settings.REVIEW_TEMPLATE_NAME else []
    wamid = whatsapp.send(wa_id, whatsapp.template_payload(name, language, params, header_image, payloads))
    preview = _render(body, params) if body else f'[Template: {name}]'
    msg = _record_out(contact, 'admin', 'template', preview, wamid)
    return ok(201, message=msg.to_dict(), contact=contact.to_dict(timezone.now()))


REVIEW_ASK = {
    'en': "Hello {name}! 🙏 Thank you for choosing AJ Technologies. Could you share a short review of your experience? It really helps us.",
    'ta': "வணக்கம் {name}! 🙏 AJ Technologies-ஐத் தேர்ந்தெடுத்ததற்கு நன்றி. உங்கள் அனுபவத்தைப் பற்றி ஒரு சிறு விமர்சனம் பகிர முடியுமா? இது எங்களுக்குப் பெரிதும் உதவும்.",
    'tanglish': "Vanakkam {name}! 🙏 AJ Technologies-ah choose pannadhukku nandri. Unga experience pathi oru chinna review share panna mudiyumaa? Engalukku romba help-ah irukkum.",
}
REVIEW_BUTTON = {'en': '⭐ Write a review', 'ta': '⭐ விமர்சனம் எழுது', 'tanglish': '⭐ Review ezhudhu'}


@api(['POST'])
@_wa_guard
def wa_review_request(request, wa_id):
    contact = _chat(wa_id)
    now = timezone.now()
    first = (contact.name or contact.profile_name or '').split(' ')[0]
    if contact.window_open(now):
        lang = contact.language if contact.language in REVIEW_ASK else 'en'
        text = REVIEW_ASK[lang].format(name=first or ('there' if lang == 'en' else '')).replace(' !', '!')
        wamid = whatsapp.send(wa_id, whatsapp.buttons_payload(text, [('rv:start', REVIEW_BUTTON[lang])]))
        msg = _record_out(contact, 'admin', 'interactive', f'{text}\n[{REVIEW_BUTTON[lang]}]', wamid)
        via = 'message'
    else:
        wamid = whatsapp.send(wa_id, whatsapp.template_payload(
            settings.REVIEW_TEMPLATE_NAME, settings.REVIEW_TEMPLATE_LANG, [first or 'there'], '', ['rv:start']))
        msg = _record_out(contact, 'admin', 'template', f'[Template: {settings.REVIEW_TEMPLATE_NAME}] Review request', wamid)
        via = 'template'
    return ok(message=msg.to_dict(), contact=contact.to_dict(now), via=via)


@api(['GET'])
def wa_templates(request):
    return ok(items=[t for t in whatsapp.list_templates() if t['name'] != settings.ADMIN_TEMPLATE_NAME])


@api(['GET'])
@_wa_guard
def wa_media(request, media_id):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', media_id):
        raise ApiError('Invalid file.', 404)
    msg = WaMessage.objects.filter(media_id=media_id).first()
    if not msg:
        raise ApiError('File not found.', 404)
    content, ctype = whatsapp.fetch_media(media_id)
    response = HttpResponse(content, content_type=ctype)
    response['Cache-Control'] = 'private, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    if msg.media_filename:
        safe = re.sub(r'[^\w.\- ]', '_', msg.media_filename)[:120]
        response['Content-Disposition'] = f'inline; filename="{safe}"'
    return response


@api(['GET'])
@_wa_guard
def wa_bookings(request):
    return ok(items=[b.to_dict() for b in WaBooking.objects.all()[:500]])


@api(['PATCH'])
@_wa_guard
def wa_booking(request, pk):
    booking = _get(WaBooking, pk)
    data = _json_body(request)
    values = {}
    if 'status' in data:
        if data['status'] not in WaBooking.STATUSES:
            raise ApiError('Choose a valid status.')
        values['status'] = data['status']
    if 'notes' in data:
        try:
            values['notes'] = _text(data['notes'], {'max': 5000})
        except ValueError:
            raise ApiError('Notes are too long (max 5000 characters).')
    if not values:
        return ok(item=booking.to_dict())
    try:
        with transaction.atomic():
            _save(booking, values)
    except IntegrityError:
        raise ApiError('Another call is already booked at this time.', 409)
    if values.get('status') and values['status'] != 'booked':
        with connection.cursor() as cur:
            cur.execute("""UPDATE wa_admin_alerts SET status = 'skipped', error = 'Changed in the dashboard'
                           WHERE kind IN ('call_reminder', 'cust_call_reminder') AND ref_id = %s AND status = 'pending'""",
                        [booking.pk])
    return ok(item=booking.to_dict())


def _audience():
    return (WaContact.objects.filter(opted_out=False).exclude(pk=settings.ADMIN_WA_NUMBER)
            .values_list('wa_id', flat=True))


@api(['GET', 'POST'])
@_wa_guard
def wa_broadcasts(request):
    if request.method == 'GET':
        return ok(items=[b.to_dict() for b in WaBroadcast.objects.all()[:100]], audience=_audience().count(),
                  opted_out=WaContact.objects.filter(opted_out=True).count())
    data = _json_body(request)
    name, language, params, header_image, body = _template_values(data)
    try:
        title = _text(data.get('title') or name, {'max': 120})
    except ValueError:
        raise ApiError('The title can be up to 120 characters.', errors={'title': 'max 120 characters'})
    numbers = list(_audience())
    if not numbers:
        raise ApiError('There is nobody to send to yet. Customers appear here after they message the bot.')
    with transaction.atomic():
        item = WaBroadcast.objects.create(title=title, template_name=name, template_language=language,
                                          body_preview=body, params=params, header_image_url=header_image,
                                          status='queued', total=len(numbers))
        WaBroadcastRecipient.objects.bulk_create(
            [WaBroadcastRecipient(broadcast_id=item.pk, wa_id=n) for n in numbers], batch_size=500)
    log.info('Broadcast %s queued for %s customers', item.pk, len(numbers))
    return ok(201, item=item.to_dict())


@api(['POST'])
@_wa_guard
def wa_broadcast_cancel(request, pk):
    item = _get(WaBroadcast, pk)
    if item.status in ('queued', 'sending'):
        with transaction.atomic():
            WaBroadcast.objects.filter(pk=pk).update(status='cancelled', finished_at=timezone.now())
            WaBroadcastRecipient.objects.filter(broadcast_id=pk, status='queued').update(status='skipped', error='Cancelled')
        item.refresh_from_db()
    return ok(item=item.to_dict())



# ---------------------------------------------------------------------------
# Upgrade v2: client projects, renewals, support requests (strictly per WhatsApp number)
# ---------------------------------------------------------------------------
NO_V2_TABLES = ('The new tables do not exist yet. In Supabase, open SQL Editor and run supabase_upgrade_v2.sql '
                '(from the WhatsApp bot project), then refresh this page.')
V2_TABLES = ('client_projects', 'client_renewals', 'support_tickets', 'bot_knowledge', 'bot_unanswered')


def _v2_guard(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ProgrammingError as e:
            if any(t in str(e) for t in V2_TABLES):
                raise ApiError(NO_V2_TABLES, 503, code='no_table')
            raise
    return inner


def _numbers(v, rule):
    items = v if isinstance(v, list) else re.split(r'[,\n]', str(v or ''))
    out = []
    for item in items:
        if not str(item).strip():
            continue
        d = re.sub(r'\D', '', str(item))
        if len(d) == 10:
            d = '91' + d
        if len(d) == 11 and d.startswith('0'):
            d = '91' + d[1:]
        if not 10 <= len(d) <= 15:
            raise ValueError(f'{item} is not a valid WhatsApp number')
        if d == settings.ADMIN_WA_NUMBER:
            raise ValueError('that is your own alerts number')
        if d not in out:
            out.append(d)
    if not out:
        raise ValueError('add at least one WhatsApp number')
    if len(out) > 3:
        raise ValueError('max 3 numbers')
    return out


def _percent(v, rule):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError('0 to 100')
    if not 0 <= n <= 100:
        raise ValueError('0 to 100')
    return n


def _any_date(v, rule):
    s = str(v or '').strip()
    if not s:
        if rule.get('required'):
            raise ValueError('required')
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('must be a date like 2026-10-28')


def _project_id(v, rule):
    try:
        pk = int(v)
    except (TypeError, ValueError):
        raise ValueError('choose a project')
    if not ClientProject.objects.filter(pk=pk).exists():
        raise ValueError('project not found')
    return pk


CLIENT_PROJECT_FIELDS = {
    'client_name':   (_text,    {'max': 120, 'required': True}),
    'business_name': (_text,    {'max': 160}),
    'wa_ids':        (_numbers, {}),
    'title':         (_text,    {'max': 160, 'required': True}),
    'service':       (_text,    {'max': 80}),
    'stage':         (_choice,  {'choices': ClientProject.STAGES}),
    'progress':      (_percent, {}),
    'client_note':   (_text,    {'max': 2000}),
    'private_notes': (_text,    {'max': 5000}),
    'live_url':      (_url,     {'max': 300}),
    'start_date':    (_any_date, {}),
    'is_active':     (_bool,    {}),
}
CLIENT_PROJECT_FIELDS['wa_ids'][1]['required'] = True

RENEWAL_FIELDS = {
    'project_id':  (_project_id, {'required': True}),
    'item':        (_choice,     {'choices': ClientRenewal.ITEMS}),
    'label':       (_text,       {'max': 160}),
    'expiry_date': (_any_date,   {'required': True}),
    'amount_text': (_text,       {'max': 60}),
    'auto_remind': (_bool,       {}),
    'status':      (_choice,     {'choices': ClientRenewal.STATUSES}),
}

TICKET_FIELDS = {
    'status':        (_choice, {'choices': SupportTicket.STATUSES}),
    'priority':      (_choice, {'choices': SupportTicket.PRIORITIES}),
    'client_update': (_text,   {'max': 1000}),
    'private_notes': (_text,   {'max': 5000}),
}

KNOWLEDGE_FIELDS = {
    'kind':       (_choice, {'choices': BotKnowledge.KINDS}),
    'question':   (_text,   {'max': 300}),
    'answer':     (_text,   {'max': 3000, 'required': True}),
    'is_active':  (_bool,   {}),
    'sort_order': (_int,    {}),
}

# Messages to clients while their 24-hour window is open (otherwise the approved templates are used)
STAGE_LABEL = {
    'en': {'requirement': 'Requirements', 'design': 'Design', 'development': 'Development', 'testing': 'Testing',
           'launch': 'Launch', 'live': 'Live ✅', 'support': 'Support & maintenance', 'on_hold': 'On hold'},
    'ta': {'requirement': 'தேவைகள்', 'design': 'வடிவமைப்பு', 'development': 'உருவாக்கம்', 'testing': 'சோதனை',
           'launch': 'வெளியீடு', 'live': 'நேரலையில் ✅', 'support': 'ஆதரவு & பராமரிப்பு', 'on_hold': 'நிறுத்தி வைக்கப்பட்டது'},
}
TICKET_LABEL = {
    'en': {'open': 'Received', 'in_progress': 'In progress', 'waiting': 'Waiting for your reply',
           'resolved': 'Resolved ✅', 'closed': 'Closed'},
    'ta': {'open': 'பெறப்பட்டது', 'in_progress': 'நடைபெறுகிறது', 'waiting': 'உங்கள் பதிலுக்காகக் காத்திருக்கிறது',
           'resolved': 'தீர்க்கப்பட்டது ✅', 'closed': 'மூடப்பட்டது'},
}
MSG = {
    'project': {'en': '📊 Update on your project *{title}*: *{stage}* ({progress}%)\n{note}',
                'ta': '📊 உங்கள் திட்டம் *{title}* பற்றிய தகவல்: *{stage}* ({progress}%)\n{note}',
                'tanglish': '📊 Unga project *{title}* update: *{stage}* ({progress}%)\n{note}'},
    'ticket': {'en': '🛠️ Update on your support request *#{id}*: *{status}*\n{note}',
               'ta': '🛠️ உங்கள் உதவி கோரிக்கை *#{id}* பற்றிய தகவல்: *{status}*\n{note}',
               'tanglish': '🛠️ Unga support request *#{id}* update: *{status}*\n{note}'},
    'b_status': {'en': '📊 My project', 'ta': '📊 என் திட்டம்', 'tanglish': '📊 En project'},
    'b_requests': {'en': '📋 My requests', 'ta': '📋 என் கோரிக்கைகள்', 'tanglish': '📋 En requests'},
    'b_menu': {'en': '🏠 Menu', 'ta': '🏠 மெனு', 'tanglish': '🏠 Menu'},
}


def _lang3(contact):
    return contact.language if contact.language in ('en', 'ta', 'tanglish') else 'en'


def _notify(wa_id, text, buttons, template, params, payloads, preview):
    """Send to one client: free message (with buttons) inside 24 hours, otherwise the approved template."""
    contact, _ = WaContact.objects.get_or_create(pk=wa_id)
    if contact.window_open(timezone.now()):
        wamid = whatsapp.send(wa_id, whatsapp.buttons_payload(text, buttons))
        _record_out(contact, 'admin', 'interactive', text, wamid, clear=False)
        return 'message'
    wamid = whatsapp.send(wa_id, whatsapp.template_payload(template, settings.TPL_LANG, params, '', payloads))
    _record_out(contact, 'admin', 'template', preview, wamid, clear=False)
    return 'template'


def _first(name):
    return (name or '').strip().split(' ')[0] or 'there'


def notify_project(p, note=''):
    note = (note or p.client_note or '').strip()
    results = []
    for wa_id in p.wa_ids:
        contact, _ = WaContact.objects.get_or_create(pk=wa_id)
        L = _lang3(contact)
        stage = STAGE_LABEL.get(L, STAGE_LABEL['en'])[p.stage]
        text = MSG['project'][L].format(title=p.title, stage=stage, progress=p.progress, note=note).strip()
        line = f"{STAGE_LABEL['en'][p.stage]} ({p.progress}%). {note}".strip()
        results.append(_notify(wa_id, text, [('m:project', MSG['b_status'][L]), ('m:menu', MSG['b_menu'][L])],
                               settings.TPL_PROJECT_UPDATE, [_first(contact.name or p.client_name), p.title, line],
                               ['m:project'], f'[Template {settings.TPL_PROJECT_UPDATE}] {p.title}: {line}'))
    return results


def notify_ticket(tk, note=''):
    contact, _ = WaContact.objects.get_or_create(pk=tk.wa_id)
    L = _lang3(contact)
    status = TICKET_LABEL.get(L, TICKET_LABEL['en'])[tk.status]
    text = MSG['ticket'][L].format(id=tk.pk, status=status, note=note or '').strip()
    line = f"{TICKET_LABEL['en'][tk.status]}. {note}".strip()
    return _notify(tk.wa_id, text, [('sp:list', MSG['b_requests'][L]), ('m:menu', MSG['b_menu'][L])],
                   settings.TPL_TICKET_UPDATE, [_first(contact.name or tk.client_name), f'#{tk.pk}', line],
                   ['sp:list'], f'[Template {settings.TPL_TICKET_UPDATE}] Request #{tk.pk}: {line}')


@api(['GET', 'POST'])
@_v2_guard
def client_projects(request):
    if request.method == 'GET':
        items = [p.to_dict() for p in ClientProject.objects.all()]
        open_counts = {}
        for row in SupportTicket.objects.exclude(status__in=('resolved', 'closed')).values('project_id'):
            open_counts[row['project_id']] = open_counts.get(row['project_id'], 0) + 1
        for item in items:
            item['open_tickets'] = open_counts.get(item['id'], 0)
        return ok(items=items)
    values = _clean(CLIENT_PROJECT_FIELDS, _json_body(request), partial=False)
    item = ClientProject.objects.create(**values)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
@_v2_guard
def client_project(request, pk):
    item = _get(ClientProject, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(CLIENT_PROJECT_FIELDS, _json_body(request), partial=True)
    if values:
        _save(item, values)
    return ok(item=item.to_dict())


@api(['POST'])
@_v2_guard
def client_project_notify(request, pk):
    item = _get(ClientProject, pk)
    note = str(_json_body(request).get('note') or '').strip()[:1000]
    if note and note != item.client_note:
        _save(item, {'client_note': note})
    via = notify_project(item, note)
    return ok(item=item.to_dict(), via=via)


@api(['GET', 'POST'])
@_v2_guard
def client_renewals(request):
    if request.method == 'GET':
        return ok(items=[r.to_dict() for r in ClientRenewal.objects.all()])
    values = _clean(RENEWAL_FIELDS, _json_body(request), partial=False)
    item = ClientRenewal.objects.create(**values)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
@_v2_guard
def client_renewal(request, pk):
    item = _get(ClientRenewal, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(RENEWAL_FIELDS, _json_body(request), partial=True)
    if 'expiry_date' in values and values['expiry_date'] != item.expiry_date:
        # a new expiry date (e.g. after renewing): reminders start again for the new date
        values.update(reminded_30_at=None, reminded_7_at=None, reminded_1_at=None)
        values.setdefault('status', 'active')
    if values:
        _save(item, values)
    return ok(item=item.to_dict())


@api(['GET'])
@_v2_guard
def client_tickets(request):
    return ok(items=[t.to_dict() for t in SupportTicket.objects.all()[:500]])


@api(['PATCH'])
@_v2_guard
def client_ticket(request, pk):
    item = _get(SupportTicket, pk)
    data = _json_body(request)
    values = _clean(TICKET_FIELDS, data, partial=True)
    if 'status' in values:
        values['resolved_at'] = (item.resolved_at or timezone.now()) if values['status'] in ('resolved', 'closed') else None
    if values:
        _save(item, values)
    via = ''
    if data.get('notify') is True:
        via = notify_ticket(item, values.get('client_update', '') or '')
    return ok(item=item.to_dict(), via=via)


# ---------------------------------------------------------------------------
# Upgrade v2: bot knowledge (FAQs) + questions the bot could not answer
# ---------------------------------------------------------------------------
@api(['GET', 'POST'])
@_v2_guard
def knowledge(request):
    if request.method == 'GET':
        return ok(items=[k.to_dict() for k in BotKnowledge.objects.all()],
                  unanswered=[u.to_dict() for u in BotUnanswered.objects.filter(status='pending')[:100]])
    data = _json_body(request)
    values = _clean(KNOWLEDGE_FIELDS, data, partial=False)
    if values.get('kind', 'faq') == 'faq' and not values.get('question'):
        raise ApiError('Please fix the highlighted fields.', 400, errors={'question': 'required for an FAQ'})
    item = BotKnowledge.objects.create(**values)
    uid = data.get('unanswered_id')
    if isinstance(uid, int):
        BotUnanswered.objects.filter(pk=uid).update(status='answered', knowledge_id=item.pk)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
@_v2_guard
def knowledge_item(request, pk):
    item = _get(BotKnowledge, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(KNOWLEDGE_FIELDS, _json_body(request), partial=True)
    if values:
        _save(item, values)
    return ok(item=item.to_dict())


@api(['PATCH'])
@_v2_guard
def unanswered_item(request, pk):
    status_value = _json_body(request).get('status')
    if status_value not in ('pending', 'ignored', 'answered'):
        raise ApiError('Invalid status.')
    BotUnanswered.objects.filter(pk=pk).update(status=status_value)
    return ok()


# ---------------------------------------------------------------------------
# Upgrade v2: reports (India time)
# ---------------------------------------------------------------------------
@api(['GET'])
@_wa_guard
def reports(request):
    try:
        days = max(1, min(int(request.GET.get('days', 7)), 365))
    except ValueError:
        days = 7
    ist_day = "(created_at AT TIME ZONE 'Asia/Kolkata')::date"
    since = f"{ist_day} > (now() AT TIME ZONE 'Asia/Kolkata')::date - %s"
    admin = settings.ADMIN_WA_NUMBER
    out = {'days': days}
    with connection.cursor() as cur:
        cur.execute(f"""SELECT count(*), count(*) FILTER (WHERE source = 'bot'), count(*) FILTER (WHERE source = 'home'),
                               count(*) FILTER (WHERE source = 'contact'), count(*) FILTER (WHERE submitted_via = 'whatsapp'),
                               count(*) FILTER (WHERE status <> 'new'), count(*) FILTER (WHERE status = 'won'),
                               count(*) FILTER (WHERE status = 'closed')
                        FROM contact_enquiries WHERE {since}""", [days])
        r = cur.fetchone()
        out['leads'] = dict(zip(['total', 'bot', 'home', 'contact', 'wa_button', 'contacted', 'won', 'closed'], r))
        cur.execute(f"""SELECT {ist_day} AS d, count(*) FROM contact_enquiries WHERE {since} GROUP BY 1 ORDER BY 1""", [days])
        out['per_day'] = [{'date': d.isoformat(), 'n': n} for d, n in cur.fetchall()]
        cur.execute(f"""SELECT s, count(*) FROM contact_enquiries, jsonb_array_elements_text(services) s
                        WHERE {since} GROUP BY s ORDER BY 2 DESC LIMIT 8""", [days])
        out['services'] = [{'name': s, 'n': n} for s, n in cur.fetchall()]
        try:
            cur.execute(f"""SELECT extract(hour FROM created_at AT TIME ZONE 'Asia/Kolkata')::int, count(*)
                            FROM wa_messages WHERE direction = 'in' AND wa_id <> %s AND {since} GROUP BY 1""", [admin, days])
            hours = dict(cur.fetchall())
            out['hours'] = [hours.get(h, 0) for h in range(24)]
            cur.execute(f"""SELECT (SELECT count(*) FROM wa_contacts WHERE wa_id <> %s AND {since}),
                                   (SELECT count(*) FROM wa_messages WHERE direction = 'in' AND wa_id <> %s AND {since}),
                                   (SELECT count(*) FROM wa_messages WHERE direction = 'out' AND sender = 'bot' AND {since}),
                                   (SELECT count(*) FROM wa_messages WHERE direction = 'out' AND sender = 'admin' AND {since}),
                                   (SELECT count(*) FROM wa_bookings WHERE {since}),
                                   (SELECT count(*) FROM wa_bookings WHERE {since} AND status = 'done')""",
                        [admin, days, admin, days, days, days, days, days])
            out['chats'] = dict(zip(['new_chats', 'messages_in', 'bot_replies', 'your_replies', 'calls', 'calls_done'],
                                    cur.fetchone()))
        except ProgrammingError:
            connection.rollback() if not connection.get_autocommit() else None
            out['hours'], out['chats'] = [0] * 24, {}
        try:
            cur.execute(f"""SELECT count(*), count(*) FILTER (WHERE status IN ('resolved', 'closed'))
                            FROM support_tickets WHERE {since}""", [days])
            out['tickets'] = dict(zip(['new', 'resolved'], cur.fetchone()))
        except ProgrammingError:
            out['tickets'] = {'new': 0, 'resolved': 0}
    return ok(**out)