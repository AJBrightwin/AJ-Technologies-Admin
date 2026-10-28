"""
WhatsApp Cloud API helper for the dashboard: your replies, template messages,
the list of approved templates and customer photos / voice notes / files.

Uses the same Meta token and phone number as the WhatsApp bot
(META_ACCESS_TOKEN, PHONE_NUMBER_ID, WABA_ID in backend/.env). Server only.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class WhatsAppError(Exception):
    """Raised when WhatsApp is not set up or Meta refuses a request."""


def is_configured():
    return bool(settings.META_ACCESS_TOKEN and settings.PHONE_NUMBER_ID)


def _url(path):
    return f'{settings.WA_GRAPH_BASE}/{settings.WA_GRAPH_VERSION}/{path}'


def _meta_error(raw, status):
    try:
        err = json.loads(raw).get('error', {})
    except ValueError:
        return f'WhatsApp error {status}.'
    code = err.get('code')
    details = (err.get('error_data') or {}).get('details', '')
    message = err.get('message', 'Unknown error')
    hints = {
        190: 'The Meta access token has expired or is wrong. Create a permanent System User token and update META_ACCESS_TOKEN.',
        131047: 'More than 24 hours have passed since the customer last messaged. Send an approved template instead.',
        132001: 'This template is not approved yet, or the name / language is wrong.',
        131026: 'This number is not on WhatsApp, or cannot receive messages.',
        100: 'WhatsApp did not accept the request. Check the template values.',
    }
    text = f'{message} ({details})' if details and details not in message else message
    return f'{hints[code]} [{code}: {text}]' if code in hints else f'WhatsApp: {text} [{code}]'


def _request(method, url, body=None, timeout=25, raw=False):
    if not is_configured():
        raise WhatsAppError('WhatsApp is not set up here. Add META_ACCESS_TOKEN and PHONE_NUMBER_ID '
                            '(the same values as the bot) to backend/.env and restart.')
    headers = {'Authorization': f'Bearer {settings.META_ACCESS_TOKEN}'}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            content = res.read()
            return (content, res.headers.get('Content-Type', '')) if raw else json.loads(content or b'{}')
    except urllib.error.HTTPError as e:
        raise WhatsAppError(_meta_error(e.read().decode('utf-8', 'replace'), e.code))
    except (urllib.error.URLError, TimeoutError) as e:
        raise WhatsAppError(f'Could not reach WhatsApp ({getattr(e, "reason", e)}). Check your internet and try again.')


def send(to, payload):
    """Send one message. Returns the WhatsApp message id."""
    res = _request('POST', _url(f'{settings.PHONE_NUMBER_ID}/messages'),
                   {'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': to, **payload})
    try:
        return res['messages'][0]['id']
    except (KeyError, IndexError, TypeError):
        raise WhatsAppError('WhatsApp did not confirm the message. Please try again.')


def text_payload(text):
    return {'type': 'text', 'text': {'body': text, 'preview_url': 'http' in text}}


def buttons_payload(body, buttons):
    return {'type': 'interactive', 'interactive': {
        'type': 'button', 'body': {'text': body[:1024]},
        'action': {'buttons': [{'type': 'reply', 'reply': {'id': i, 'title': t[:20]}} for i, t in buttons[:3]]}}}


def template_param(value):
    """Template values cannot contain new lines, tabs or more than 4 spaces in a row."""
    text = ' '.join(str(value if value not in (None, '') else '-').split())
    return text[:300] or '-'


def template_payload(name, language, params=(), header_image='', quick_reply_payloads=()):
    components = []
    if header_image:
        components.append({'type': 'header', 'parameters': [{'type': 'image', 'image': {'link': header_image}}]})
    if params:
        components.append({'type': 'body', 'parameters': [{'type': 'text', 'text': template_param(p)} for p in params]})
    for index, payload in enumerate(quick_reply_payloads):
        components.append({'type': 'button', 'sub_type': 'quick_reply', 'index': str(index),
                           'parameters': [{'type': 'payload', 'payload': payload}]})
    template = {'name': name, 'language': {'code': language}}
    if components:
        template['components'] = components
    return {'type': 'template', 'template': template}


def list_templates():
    """Approved message templates from Meta, simplified for the dashboard."""
    if not settings.WABA_ID:
        raise WhatsAppError('Add WABA_ID (WhatsApp Business Account ID, from Meta > WhatsApp > API Setup) '
                            'to backend/.env to load your templates.')
    out, url = [], _url(f'{settings.WABA_ID}/message_templates?' + urllib.parse.urlencode(
        {'fields': 'name,language,status,category,components,parameter_format', 'limit': 100}))
    for _ in range(5):                                     # up to 500 templates
        res = _request('GET', url)
        for t in res.get('data') or []:
            if t.get('status') != 'APPROVED':
                continue
            item = {'name': t['name'], 'language': t.get('language', 'en'), 'category': t.get('category', ''),
                    'header': '', 'header_text': '', 'body': '', 'footer': '', 'buttons': [], 'params': 0,
                    'supported': t.get('parameter_format', 'POSITIONAL') != 'NAMED'}
            for comp in t.get('components') or []:
                kind = comp.get('type')
                if kind == 'HEADER':
                    item['header'] = comp.get('format', 'TEXT')
                    item['header_text'] = comp.get('text', '')
                    if item['header'] == 'TEXT' and '{{' in item['header_text']:
                        item['supported'] = False
                    if item['header'] in ('VIDEO', 'DOCUMENT', 'LOCATION'):
                        item['supported'] = False
                elif kind == 'BODY':
                    item['body'] = comp.get('text', '')
                    nums = [int(n) for n in re.findall(r'\{\{\s*(\d+)\s*\}\}', item['body'])]
                    item['params'] = max(nums) if nums else 0
                elif kind == 'FOOTER':
                    item['footer'] = comp.get('text', '')
                elif kind == 'BUTTONS':
                    item['buttons'] = [{'type': b.get('type', ''), 'text': b.get('text', '')} for b in comp.get('buttons') or []]
                    if any(b.get('type') in ('URL',) and '{{' in (b.get('url') or '') for b in comp.get('buttons') or []):
                        item['supported'] = False
                    if any(b.get('type') in ('COPY_CODE', 'FLOW', 'OTP', 'CATALOG', 'MPM') for b in comp.get('buttons') or []):
                        item['supported'] = False
            out.append(item)
        url = ((res.get('paging') or {}).get('next')) or ''
        if not url:
            break
    return sorted(out, key=lambda t: (t['name'], t['language']))


def fetch_media(media_id):
    """Customer photo / voice note / file from WhatsApp. Returns (bytes, content_type)."""
    info = _request('GET', _url(media_id))
    if not info.get('url'):
        raise WhatsAppError('WhatsApp no longer has this file (media is kept for about 30 days).')
    if int(info.get('file_size') or 0) > 25 * 1024 * 1024:
        raise WhatsAppError('This file is too large to show here.')
    content, ctype = _request('GET', info['url'], timeout=60, raw=True)
    return content, info.get('mime_type') or ctype or 'application/octet-stream'