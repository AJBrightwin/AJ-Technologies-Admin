"""
Client portal controls for the dashboard (the client sees these at ajtechnologiesltd.com/my/).
Tables: supabase_portal.sql.

    GET/PATCH   /api/portal/projects/<id>/              portal view of a project; PATCH preview_url, files_link,
                                                        files_ready, files_paid (cash / bank), lock again
    POST        /api/portal/projects/<id>/updates/      post an update {body, image_path, notify}
    DELETE      /api/portal/updates/<id>/
    POST        /api/portal/projects/<id>/approvals/    ask for approval {title, details, link, image_path, notify}
    POST        /api/portal/approvals/<id>/reopen/      ask again after changes
    DELETE      /api/portal/approvals/<id>/
    POST        /api/portal/projects/<id>/requests/     "what we need" {title, details, notify}
    PATCH       /api/portal/requests/<id>/              {status: open | uploaded | done}
    DELETE      /api/portal/requests/<id>/
    POST        /api/portal/projects/<id>/link/         send the portal login link to the client's numbers
    GET         /api/portal/tickets/<id>/files/         screenshots a client attached in the portal
    GET         /api/portal/file/?path=...              open an uploaded file (private, 5-minute link)
"""
import hashlib
import json
import logging
import re
import secrets
import urllib.parse

from django.conf import settings
from django.db import ProgrammingError, connection
from django.http import HttpResponseRedirect
from django.utils import timezone
from functools import wraps

from . import storage, whatsapp
from .models import WaContact
from .views import ApiError, _first, _json_body, _notify, _record_out, api, ok

log = logging.getLogger(__name__)
NO_PORTAL = ('The client portal tables do not exist yet. In Supabase, open SQL Editor, run supabase_portal.sql, '
             'then refresh this page.')
FILES_PRICE = 7000


def _guard(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ProgrammingError as e:
            if any(w in str(e) for w in ('portal_', 'project_updates', 'project_approvals', 'project_requests',
                                          'preview_url', 'files_link', 'files_ready')):
                raise ApiError(NO_PORTAL, 503, code='no_table')
            raise
    return inner


def _rows(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _row(sql, params=()):
    r = _rows(sql, params)
    return r[0] if r else None


def _jl(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return []
    return v or []


def _iso(v):
    return v.isoformat() if v else ''


def _txt(data, key, limit, required=False, label=''):
    v = str(data.get(key) or '').strip()
    if required and not v:
        raise ApiError('Please fill in the highlighted fields.', 400, errors={key: 'required'})
    if len(v) > limit:
        raise ApiError(f'{label or key} is too long ({limit} characters at most).', 400, errors={key: 'too long'})
    return v


def _link(data, key):
    v = _txt(data, key, 1000)
    if v and not re.match(r'^https?://\S+$', v, re.I):
        raise ApiError('Links must start with https://', 400, errors={key: 'not a link'})
    return v


def _image(data):
    v = _txt(data, 'image_path', 300)
    if v and (not v.startswith(settings.SUPABASE_IMAGE_FOLDER + '/') or '..' in v):
        raise ApiError('Choose the photo from your uploaded images.', 400, errors={'image_path': 'invalid'})
    return v


def _project(pk):
    p = _row("""SELECT id, client_name, business_name, wa_ids, title, stage, preview_url, files_link, files_ready,
                       files_ready_at, files_paid, files_invoice_id, portal_seen_at
                FROM client_projects WHERE id = %s""", [pk])
    if not p:
        raise ApiError('Project not found.', 404)
    return p


def _image_url(path):
    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{settings.SUPABASE_STORAGE_BUCKET}/{path}" if path else ''


def _file_url(path):
    return '/api/portal/file/?path=' + urllib.parse.quote(path)


def _files_state(p):
    inv = _row("SELECT id, number, status, total, amount_paid FROM billing_documents WHERE id = %s",
               [p['files_invoice_id']]) if p['files_invoice_id'] else None
    if inv and inv['status'] == 'cancelled':
        inv = None
    paid = bool(p['files_paid'] or (inv and inv['status'] == 'paid'))
    ready = bool(p['files_ready'] and p['files_link'])
    return {'paid': paid, 'paid_by': 'razorpay' if inv and inv['status'] == 'paid' else 'manual' if p['files_paid'] else '',
            'ready': ready, 'state': 'ready' if paid and ready else 'paid' if paid else 'invoiced' if inv else 'locked',
            'invoice': {'id': inv['id'], 'number': inv['number'], 'status': inv['status'],
                        'balance': float(inv['total'] - inv['amount_paid'])} if inv else None,
            'price': FILES_PRICE}


# ---------------------------------------------------------------------------
# Telling the client (free message inside 24 hours, otherwise your approved project_update template)
# ---------------------------------------------------------------------------
def _tell(p, what, line):
    """what: the free WhatsApp text; line: one line for the template."""
    out = []
    for wa_id in p['wa_ids'] or []:
        contact, _ = WaContact.objects.get_or_create(pk=wa_id)
        text = f"🔐 *{p['title']}*\n\n{what}\n\nTap *My portal* (or type LOGIN) to open your client portal."
        try:
            out.append(_notify(wa_id, text, [('m:portal', '🔐 My portal'), ('m:project', '📊 Project status')],
                               settings.TPL_PROJECT_UPDATE, [_first(contact.name or p['client_name']), p['title'],
                                                             f'{line} Reply LOGIN to open your client portal.'],
                               ['m:project'], f"[Template {settings.TPL_PROJECT_UPDATE}] {p['title']}: {line}"))
        except Exception as e:                       # never lose the saved item because WhatsApp failed
            log.warning('Portal notice to %s failed: %s', wa_id, e)
            out.append('failed')
    return out


# ---------------------------------------------------------------------------
# Project portal view
# ---------------------------------------------------------------------------
@api(['GET', 'PATCH'])
@_guard
def portal_project(request, pk):
    p = _project(pk)
    if request.method == 'PATCH':
        data = _json_body(request)
        sets, vals, notify_ready = [], [], False
        if 'preview_url' in data:
            sets.append('preview_url = %s'); vals.append(_link(data, 'preview_url'))
        if 'files_link' in data:
            sets.append('files_link = %s'); vals.append(_link(data, 'files_link'))
        if 'files_paid' in data:
            sets.append('files_paid = %s'); vals.append(bool(data.get('files_paid')))
        if 'files_ready' in data:
            ready = bool(data.get('files_ready'))
            link = _link(data, 'files_link') if 'files_link' in data else p['files_link']
            if ready and not link:
                raise ApiError('Paste the link to the files first (Google Drive, OneDrive...).', 400,
                               errors={'files_link': 'required'})
            sets.append('files_ready = %s'); vals.append(ready)
            sets.append('files_ready_at = CASE WHEN %s THEN COALESCE(files_ready_at, now()) ELSE NULL END'); vals.append(ready)
            notify_ready = ready and not p['files_ready']
        if sets:
            _rows(f"UPDATE client_projects SET {', '.join(sets)}, updated_at = now() WHERE id = %s", vals + [pk])
        p = _project(pk)
        st = _files_state(p)
        if notify_ready and st['paid'] and data.get('notify', True):
            _tell(p, '📦 Your project files are ready! Open your client portal to download them.',
                  'Your project files are ready to download.')
    updates = _rows("SELECT id, body, image_path, created_at FROM project_updates WHERE project_id = %s "
                    "ORDER BY created_at DESC", [pk])
    approvals = _rows("""SELECT id, title, details, link, image_path, status, client_comment, decided_by, decided_at,
                                created_at FROM project_approvals WHERE project_id = %s ORDER BY created_at DESC""", [pk])
    reqs = _rows("""SELECT id, title, details, status, files, note, created_at, updated_at FROM project_requests
                    WHERE project_id = %s ORDER BY created_at DESC""", [pk])
    activity = _rows("""SELECT wa_id, action, detail, created_at FROM portal_activity
                        WHERE project_id = %s OR (project_id IS NULL AND wa_id = ANY(%s))
                        ORDER BY created_at DESC LIMIT 15""", [pk, p['wa_ids'] or []])
    sessions = _row("""SELECT count(*) AS n, max(last_seen_at) AS seen FROM portal_sessions
                       WHERE wa_id = ANY(%s) AND revoked_at IS NULL AND expires_at > now()""", [p['wa_ids'] or []])
    profiles = _rows("SELECT wa_id, contact_name, business_name, email, address, gstin FROM portal_profiles "
                     "WHERE wa_id = ANY(%s)", [p['wa_ids'] or []])
    return ok(item={
        'id': p['id'], 'title': p['title'], 'client_name': p['client_name'], 'wa_ids': p['wa_ids'] or [],
        'preview_url': p['preview_url'], 'files_link': p['files_link'], 'files_ready': p['files_ready'],
        'files_paid': p['files_paid'], 'files': _files_state(p), 'seen_at': _iso(p['portal_seen_at']),
        'devices': sessions['n'] if sessions else 0, 'portal_url': f'{settings.SITE_URL}/my/',
        'updates': [{'id': u['id'], 'body': u['body'], 'image': _image_url(u['image_path']), 'at': _iso(u['created_at'])}
                    for u in updates],
        'approvals': [{'id': a['id'], 'title': a['title'], 'details': a['details'], 'link': a['link'],
                       'image': _image_url(a['image_path']), 'status': a['status'], 'comment': a['client_comment'],
                       'decided_by': a['decided_by'], 'decided_at': _iso(a['decided_at']), 'at': _iso(a['created_at'])}
                      for a in approvals],
        'requests': [{'id': r['id'], 'title': r['title'], 'details': r['details'], 'status': r['status'],
                      'note': r['note'], 'at': _iso(r['created_at']), 'updated_at': _iso(r['updated_at']),
                      'files': [{'name': f.get('name', ''), 'size': f.get('size', 0), 'url': _file_url(f.get('path', ''))}
                                for f in _jl(r['files']) if isinstance(f, dict)]} for r in reqs],
        'activity': [{'wa_id': a['wa_id'], 'action': a['action'], 'detail': a['detail'], 'at': _iso(a['created_at'])}
                     for a in activity],
        'profiles': profiles,
    })


@api(['POST'])
@_guard
def portal_update_add(request, pk):
    p = _project(pk)
    data = _json_body(request)
    body = _txt(data, 'body', 4000, required=True, label='The update')
    image = _image(data)
    u = _row("INSERT INTO project_updates (project_id, body, image_path) VALUES (%s, %s, %s) RETURNING id",
             [pk, body, image])
    sent = _tell(p, f'📢 New update: {body[:700]}', f'New update: {body[:180]}') if data.get('notify', True) else []
    return ok(201, id=u['id'], sent=sent)


@api(['DELETE'])
@_guard
def portal_update(request, pk):
    _rows('DELETE FROM project_updates WHERE id = %s', [pk])
    return ok()


@api(['POST'])
@_guard
def portal_approval_add(request, pk):
    p = _project(pk)
    data = _json_body(request)
    title = _txt(data, 'title', 160, required=True, label='Title')
    a = _row("""INSERT INTO project_approvals (project_id, title, details, link, image_path)
                VALUES (%s, %s, %s, %s, %s) RETURNING id""",
             [pk, title, _txt(data, 'details', 3000), _link(data, 'link'), _image(data)])
    sent = _tell(p, f'✅ Please review and approve: *{title}*', f'Please review and approve: {title}.') \
        if data.get('notify', True) else []
    return ok(201, id=a['id'], sent=sent)


@api(['POST', 'DELETE'])
@_guard
def portal_approval(request, pk, action=''):
    a = _row('SELECT id, project_id, title FROM project_approvals WHERE id = %s', [pk])
    if not a:
        raise ApiError('Not found.', 404)
    if request.method == 'DELETE':
        _rows('DELETE FROM project_approvals WHERE id = %s', [pk])
        return ok()
    data = _json_body(request)
    _rows("""UPDATE project_approvals SET status = 'pending', decided_at = NULL, decided_by = '',
             details = CASE WHEN %s = '' THEN details ELSE %s END WHERE id = %s""",
          [_txt(data, 'details', 3000), _txt(data, 'details', 3000), pk])
    sent = _tell(_project(a['project_id']), f"🔁 Updated version ready. Please review again: *{a['title']}*",
                 f"Updated version ready, please review again: {a['title']}.") if data.get('notify', True) else []
    return ok(sent=sent)


@api(['POST'])
@_guard
def portal_request_add(request, pk):
    p = _project(pk)
    data = _json_body(request)
    title = _txt(data, 'title', 160, required=True, label='Title')
    r = _row("INSERT INTO project_requests (project_id, title, details) VALUES (%s, %s, %s) RETURNING id",
             [pk, title, _txt(data, 'details', 3000)])
    sent = _tell(p, f'📎 We need from you: *{title}*\nYou can upload it in your client portal.',
                 f'We need from you: {title}. You can upload it in your client portal.') if data.get('notify', True) else []
    return ok(201, id=r['id'], sent=sent)


@api(['PATCH', 'DELETE'])
@_guard
def portal_request(request, pk):
    if request.method == 'DELETE':
        _rows('DELETE FROM project_requests WHERE id = %s', [pk])
        return ok()
    status = _json_body(request).get('status')
    if status not in ('open', 'uploaded', 'done'):
        raise ApiError('Choose a status.')
    _rows('UPDATE project_requests SET status = %s WHERE id = %s', [status, pk])
    return ok()


@api(['POST'])
@_guard
def portal_send_link(request, pk):
    """The login link to every number on the project: a one-time link inside the 24-hour window,
    otherwise the project_update template asking them to reply LOGIN (their reply opens the window, and the bot
    answers with the link at no cost)."""
    p = _project(pk)
    if not p['wa_ids']:
        raise ApiError('Add the client\'s WhatsApp number to the project first.')
    results, now = [], timezone.now()
    for wa_id in p['wa_ids']:
        contact, _ = WaContact.objects.get_or_create(pk=wa_id)
        try:
            if contact.window_open(now):
                code = secrets.token_urlsafe(32)
                _rows("INSERT INTO portal_login_tokens (wa_id, token_hash, created_by) VALUES (%s, %s, 'admin')",
                      [wa_id, hashlib.sha256(code.encode()).hexdigest()])
                body = (f"🔐 *Your client portal is ready*\n\nSee *{p['title']}*: progress, approvals, invoices, renewals "
                        f"and support, all in one place.\n\nThis link works once and expires in 15 minutes. Later, just "
                        f"type LOGIN here to get a new one.")
                wamid = whatsapp.send(wa_id, {'type': 'interactive', 'interactive': {
                    'type': 'cta_url', 'body': {'text': body},
                    'action': {'name': 'cta_url', 'parameters': {'display_text': 'Open my portal',
                                                                 'url': f'{settings.SITE_URL}/my/login/{code}/'}}}})
                _record_out(contact, 'admin', 'interactive', body + '\n[Open my portal: one-time login link]', wamid,
                            clear=False)
                results.append({'wa_id': wa_id, 'via': 'link'})
            else:
                line = 'Your client portal is ready. Reply LOGIN to get your private link.'
                wamid = whatsapp.send(wa_id, whatsapp.template_payload(
                    settings.TPL_PROJECT_UPDATE, settings.TPL_LANG,
                    [_first(contact.name or p['client_name']), p['title'], line], '', ['m:project']))
                _record_out(contact, 'admin', 'template', f'[Template {settings.TPL_PROJECT_UPDATE}] {line}', wamid,
                            clear=False)
                results.append({'wa_id': wa_id, 'via': 'template'})
        except Exception as e:
            log.warning('Portal link to %s failed: %s', wa_id, e)
            results.append({'wa_id': wa_id, 'via': 'failed', 'error': str(e)[:200]})
    if all(r['via'] == 'failed' for r in results):
        raise ApiError('WhatsApp did not send it: ' + results[0].get('error', ''), 502)
    return ok(results=results)


# ---------------------------------------------------------------------------
# Files the client uploaded (private bucket, 5-minute links)
# ---------------------------------------------------------------------------
@api(['GET'])
@_guard
def portal_ticket_files(request, pk):
    t = _row('SELECT files FROM support_tickets WHERE id = %s', [pk])
    if not t:
        raise ApiError('Not found.', 404)
    return ok(items=[{'name': f.get('name', ''), 'size': f.get('size', 0), 'url': _file_url(f.get('path', ''))}
                     for f in _jl(t['files']) if isinstance(f, dict)])


@api(['GET'])
def portal_file(request):
    path = request.GET.get('path', '')
    if not path or '..' in path or path.startswith('/') or len(path) > 400:
        raise ApiError('Invalid file.', 400)
    known = _row("""SELECT 1 FROM project_requests WHERE files @> %s::jsonb
                    UNION ALL SELECT 1 FROM support_tickets WHERE files @> %s::jsonb LIMIT 1""",
                 [json.dumps([{'path': path}]), json.dumps([{'path': path}])])
    if not known:
        raise ApiError('File not found.', 404)
    bucket = urllib.parse.quote(settings.PORTAL_UPLOAD_BUCKET)
    try:
        res = storage._request('POST', f'object/sign/{bucket}/{urllib.parse.quote(path)}',
                               data=json.dumps({'expiresIn': 300}).encode(), content_type='application/json')
    except storage.StorageError as e:
        raise ApiError(str(e), 502)
    signed = (res or {}).get('signedURL') or (res or {}).get('signedUrl') or ''
    if not signed:
        raise ApiError('Storage did not return a link. Try again.', 502)
    return HttpResponseRedirect(f'{settings.SUPABASE_URL}/storage/v1{signed}')
