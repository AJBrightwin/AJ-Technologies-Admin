"""
Upgrade v4: quotations and invoices.

    next_number(...)      AJQ-2026-0001 / AJINV-2026-0001 (per year, never repeated)
    pdf(doc, settings)    the PDF (A4) with your logo, items, totals, payment details and terms
    create_payment_link   a Razorpay payment link for the balance of an invoice (Key ID / Secret from the environment)
    send_on_whatsapp      the PDF to the client: a document message inside 24 hours, otherwise the billing_document template
"""
import base64
import io
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.conf import settings as conf
from django.db import connection
from django.utils import timezone

from . import whatsapp

log = logging.getLogger(__name__)
ASSETS = Path(__file__).resolve().parent / 'assets'


class BillingError(Exception):
    pass


def D(value):
    try:
        return Decimal(str(value if value not in (None, '') else 0)).quantize(Decimal('0.01'), ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def money(value, symbol=True):
    """Indian grouping: 1234567.5 -> ₹12,34,567.50 ; 15000 -> ₹15,000"""
    v = D(value)
    neg = v < 0
    v = abs(v)
    whole = int(v)
    frac = int((v - whole) * 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r'(\d)(?=(\d\d)+$)', r'\1,', head)
        s = f'{head},{tail}'
    if frac:
        s += f'.{frac:02d}'
    return ('-' if neg else '') + ('₹' if symbol else '') + s


def ist_today():
    return timezone.localtime().date()           # TIME_ZONE = Asia/Kolkata


# ---------------------------------------------------------------------------
# Items and totals
# ---------------------------------------------------------------------------
def clean_items(items):
    if not isinstance(items, list) or not items:
        raise ValueError('add at least one item')
    out = []
    for i, it in enumerate(items[:40], start=1):
        if not isinstance(it, dict):
            raise ValueError(f'item {i} is not valid')
        desc = ' '.join(str(it.get('description') or '').split())[:300]
        details = str(it.get('details') or '').strip()[:600]
        qty, rate = D(it.get('qty') or 1), D(it.get('rate'))
        if not desc:
            raise ValueError(f'item {i}: description is required')
        if qty <= 0 or qty > 100000:
            raise ValueError(f'item {i}: quantity must be more than 0')
        if rate < 0 or rate > Decimal('100000000'):
            raise ValueError(f'item {i}: rate is not valid')
        out.append({'description': desc, 'details': details, 'qty': float(qty), 'rate': float(rate)})
    return out


def compute_total(items, discount):
    subtotal = sum((D(i['qty']) * D(i['rate']) for i in items), Decimal(0))
    discount = D(discount)
    if discount > subtotal:
        raise ValueError('discount is more than the subtotal')
    return D(subtotal - discount)


def next_number(doc_type, s):
    prefix = (s.quote_prefix if doc_type == 'quote' else s.invoice_prefix) or ('AJQ' if doc_type == 'quote' else 'AJINV')
    prefix = re.sub(r'[^A-Za-z0-9]', '', prefix)[:10].upper() or 'AJ'
    year = ist_today().year
    head = f'{prefix}-{year}-'
    with connection.cursor() as cur:
        cur.execute("SELECT number FROM billing_documents WHERE number LIKE %s", [head + '%'])
        used = [int(m.group(1)) for (n,) in cur.fetchall() if (m := re.match(re.escape(head) + r'(\d+)$', n))]
    return f'{head}{(max(used) + 1 if used else 1):04d}'


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
_fonts = {}


def _register_fonts():
    if _fonts:
        return _fonts
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        pdfmetrics.registerFont(TTFont('AJSans', str(ASSETS / 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('AJSans-Bold', str(ASSETS / 'DejaVuSans-Bold.ttf')))
        _fonts.update(regular='AJSans', bold='AJSans-Bold', rupee=True)
    except Exception:                                 # font files missing: fall back to built-in fonts and "Rs."
        log.warning('PDF fonts not found in main/assets; using Helvetica')
        _fonts.update(regular='Helvetica', bold='Helvetica-Bold', rupee=False)
    return _fonts


STATUS_TEXT = {'draft': 'DRAFT', 'sent': '', 'accepted': 'ACCEPTED', 'rejected': 'DECLINED', 'expired': 'EXPIRED',
               'partly_paid': 'PART PAID', 'paid': 'PAID', 'cancelled': 'CANCELLED'}


def pdf(doc, s):
    """Return the PDF bytes for a BillingDocument, using BusinessSettings s."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)
    from xml.sax.saxutils import escape

    f = _register_fonts()
    cur = (lambda v: money(v)) if f['rupee'] else (lambda v: 'Rs. ' + money(v, symbol=False))
    brand, ink, muted, line, soft = (colors.HexColor('#2563eb'), colors.HexColor('#0f172a'), colors.HexColor('#64748b'),
                                     colors.HexColor('#e2e8f0'), colors.HexColor('#f1f5ff'))
    st = {
        'n': ParagraphStyle('n', fontName=f['regular'], fontSize=9.5, leading=13.5, textColor=ink),
        's': ParagraphStyle('s', fontName=f['regular'], fontSize=8.5, leading=12, textColor=muted),
        'b': ParagraphStyle('b', fontName=f['bold'], fontSize=9.5, leading=13.5, textColor=ink),
        'h': ParagraphStyle('h', fontName=f['bold'], fontSize=10, leading=14, textColor=brand, spaceBefore=4),
        'big': ParagraphStyle('big', fontName=f['bold'], fontSize=17, leading=21, textColor=ink),
        'title': ParagraphStyle('title', fontName=f['bold'], fontSize=22, leading=26, textColor=brand, alignment=TA_RIGHT),
        'r': ParagraphStyle('r', fontName=f['regular'], fontSize=9.5, leading=13.5, textColor=ink, alignment=TA_RIGHT),
        'rb': ParagraphStyle('rb', fontName=f['bold'], fontSize=9.5, leading=13.5, textColor=ink, alignment=TA_RIGHT),
        'rs': ParagraphStyle('rs', fontName=f['regular'], fontSize=8.5, leading=12, textColor=muted, alignment=TA_RIGHT),
    }
    P = lambda text, style='n': Paragraph(text, st[style])
    E = lambda text: escape(str(text or '')).replace('\n', '<br/>')
    is_quote = doc.doc_type == 'quote'
    buf = io.BytesIO()
    page_w = A4[0] - 36 * mm

    def on_page(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(brand)
        canvas.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, stroke=0, fill=1)
        canvas.setFont(f['regular'], 7.5)
        canvas.setFillColor(muted)
        foot = ' · '.join(x for x in (s.business_name, s.website, s.phone, s.email) if x)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, foot)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f'Page {canvas.getPageNumber()}')
        mark = STATUS_TEXT.get(doc.status, '')
        if mark:
            canvas.setFont(f['bold'], 54)
            canvas.setFillColor(colors.Color(0.15, 0.39, 0.92, alpha=0.07) if doc.status != 'paid'
                                else colors.Color(0.09, 0.64, 0.29, alpha=0.10))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(30)
            canvas.drawCentredString(0, 0, mark)
        canvas.restoreState()

    story = []
    # ---- header: logo + business | QUOTATION / INVOICE + number
    logo = ASSETS / 'logo.png'
    left = []
    if logo.exists():
        left.append(Image(str(logo), width=15 * mm, height=15 * mm))
    biz = [P(E(s.business_name), 'big')]
    if s.tagline:
        biz.append(P(E(s.tagline), 's'))
    contact = '<br/>'.join(E(x) for x in (s.address, s.phone, s.email, s.website) if x)
    biz.append(Spacer(1, 3))
    biz.append(P(contact, 's'))
    head_left = Table([[left[0] if left else '', biz]], colWidths=[18 * mm if left else 0.1, None])
    head_left.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    when = [('Date', doc.issue_date.strftime('%d %b %Y'))]
    if doc.due_date:
        when.append(('Valid until' if is_quote else 'Due date', doc.due_date.strftime('%d %b %Y')))
    right = [P('QUOTATION' if is_quote else 'INVOICE', 'title'), P(f'<b>{E(doc.number)}</b>', 'r')]
    right += [P(f'{k}: {v}', 'rs') for k, v in when]
    head = Table([[head_left, right]], colWidths=[page_w * 0.6, page_w * 0.4])
    head.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                              ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 8 * mm)]

    # ---- bill to + project
    to = [P('QUOTATION FOR' if is_quote else 'BILL TO', 'h'), P(f'<b>{E(doc.client_name)}</b>')]
    if doc.business_name:
        to.append(P(E(doc.business_name)))
    wa = doc.client_wa_id or ''
    wa = f'+91 {wa[2:7]} {wa[7:]}' if len(wa) == 12 and wa.startswith('91') else (('+' + wa) if wa else '')
    for x in (doc.client_address, wa, doc.client_email):
        if x:
            to.append(P(E(x), 's'))
    proj = []
    if doc.title:
        proj = [P('PROJECT', 'h'), P(f'<b>{E(doc.title)}</b>')]
    box = Table([[to, proj]], colWidths=[page_w * 0.55, page_w * 0.45])
    box.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    story += [box, Spacer(1, 6 * mm)]

    # ---- items
    rows = [[P('<b>#</b>'), P('<b>Description</b>'), P('<b>Qty</b>', 'rb'), P('<b>Rate</b>', 'rb'), P('<b>Amount</b>', 'rb')]]
    for i, it in enumerate(doc.items or [], start=1):
        qty, rate = D(it.get('qty')), D(it.get('rate'))
        desc = f"<b>{E(it.get('description'))}</b>"
        if it.get('details'):
            desc += f"<br/><font size=8.5 color='#64748b'>{E(it['details'])}</font>"
        q = f'{qty.normalize():f}' if qty == qty.to_integral() else f'{qty:f}'
        rows.append([P(str(i)), P(desc), P(q, 'r'), P(cur(rate), 'r'), P(cur(qty * rate), 'r')])
    items = Table(rows, colWidths=[9 * mm, page_w - 9 * mm - 18 * mm - 30 * mm - 32 * mm, 18 * mm, 30 * mm, 32 * mm],
                  repeatRows=1)
    items.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), soft), ('LINEBELOW', (0, 0), (-1, 0), 0.8, brand),
        ('LINEBELOW', (0, 1), (-1, -1), 0.4, line), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    story += [items, Spacer(1, 4 * mm)]

    # ---- totals
    tot = [[P('Subtotal', 'r'), P(cur(doc.subtotal), 'r')]]
    if D(doc.discount):
        tot.append([P('Discount', 'r'), P('- ' + cur(doc.discount), 'r')])
    tot.append([P('<b>Total</b>', 'rb'), P(f'<b>{cur(doc.total)}</b>', 'rb')])
    if not is_quote and D(doc.amount_paid):
        tot.append([P('Paid', 'r'), P(cur(doc.amount_paid), 'r')])
        tot.append([P('<b>Balance due</b>', 'rb'), P(f'<b>{cur(doc.balance)}</b>', 'rb')])
    total_row = 2 if D(doc.discount) else 1
    tt = Table(tot, colWidths=[page_w - 70 * mm, 40 * mm], hAlign='RIGHT')
    tt.setStyle(TableStyle([('LINEABOVE', (0, total_row), (-1, total_row), 0.8, ink),
                            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    story += [tt, Spacer(1, 2 * mm), P('No GST is charged on this ' + ('quotation.' if is_quote else 'invoice.'), 'rs'),
              Spacer(1, 6 * mm)]

    # ---- how to pay (invoices) / how to accept (quotes)
    pay = []
    if is_quote:
        pay.append(P('HOW TO ACCEPT', 'h'))
        pay.append(P('Reply <b>ACCEPT</b> on WhatsApp (or tap “Accept quote”) and our team will share the next steps.'))
    elif doc.status not in ('paid', 'cancelled') and D(doc.balance) > 0:
        pay.append(P('HOW TO PAY', 'h'))
        if doc.razorpay_link_url:
            pay.append(P(f'Pay online (UPI, cards, net banking): <link href="{E(doc.razorpay_link_url)}" color="#2563eb">'
                         f'<u>{E(doc.razorpay_link_url)}</u></link>'))
        if s.upi_id:
            pay.append(P(f'UPI: <b>{E(s.upi_id)}</b>'))
        if s.bank_details:
            pay.append(P('Bank transfer:<br/>' + E(s.bank_details)))
    if pay:
        story += [KeepTogether(pay), Spacer(1, 4 * mm)]
    if doc.notes:
        story += [KeepTogether([P('NOTES', 'h'), P(E(doc.notes))]), Spacer(1, 4 * mm)]
    terms = doc.terms or (s.quote_terms if is_quote else s.invoice_terms)
    if terms:
        story += [KeepTogether([P('TERMS', 'h'), P(E(terms), 's')]), Spacer(1, 6 * mm)]
    if s.footer_note:
        story.append(P(f'<b>{E(s.footer_note)}</b>'))

    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                      title=f'{"Quotation" if is_quote else "Invoice"} {doc.number}', author=s.business_name,
                      subject=doc.title or '').build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def filename(doc):
    kind = 'Quotation' if doc.doc_type == 'quote' else 'Invoice'
    return f'{kind}-{doc.number}.pdf'


# ---------------------------------------------------------------------------
# Razorpay payment link
# ---------------------------------------------------------------------------
def razorpay_ready():
    return bool(conf.RAZORPAY_KEY_ID and conf.RAZORPAY_KEY_SECRET)


def _razorpay(method, path, body=None):
    if not razorpay_ready():
        raise BillingError('Razorpay is not set up. Add RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in Render > Environment '
                           '(dashboard service), then try again.')
    auth = base64.b64encode(f'{conf.RAZORPAY_KEY_ID}:{conf.RAZORPAY_KEY_SECRET}'.encode()).decode()
    req = urllib.request.Request(f'{conf.RAZORPAY_API_BASE}{path}', method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            return json.loads(res.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode('utf-8', 'replace')).get('error', {})
            text = err.get('description') or err.get('code') or f'error {e.code}'
        except ValueError:
            text = f'error {e.code}'
        if e.code == 401:
            text = 'The Razorpay Key ID / Key Secret are wrong (or test keys with a live account). ' + text
        raise BillingError(f'Razorpay: {text}')
    except (urllib.error.URLError, TimeoutError) as e:
        raise BillingError(f'Could not reach Razorpay ({getattr(e, "reason", e)}). Try again.')


def create_payment_link(doc, amount=None):
    """A new payment link for `amount` (default: the balance). Any older unpaid link is cancelled."""
    amount = D(amount if amount not in (None, '') else doc.balance)
    if amount <= 0:
        raise BillingError('Nothing to pay on this invoice.')
    if amount > D(doc.balance):
        raise BillingError(f'The amount is more than the balance ({money(doc.balance)}).')
    if amount < 1:
        raise BillingError('Razorpay needs at least ₹1.')
    if doc.razorpay_link_id:
        try:
            _razorpay('POST', f'/v1/payment_links/{doc.razorpay_link_id}/cancel', {})
        except BillingError as e:
            log.info('Old payment link not cancelled: %s', e)
    customer = {'name': doc.client_name[:50]}
    if doc.client_wa_id:
        customer['contact'] = '+' + doc.client_wa_id
    if doc.client_email:
        customer['email'] = doc.client_email
    body = {
        'amount': int(amount * 100), 'currency': 'INR', 'accept_partial': False,
        'reference_id': f'{doc.number}-{timezone.now():%H%M%S}'[:40],
        'description': f'{doc.number} · {doc.title or "AJ Technologies"}'[:2048],
        'customer': customer, 'notify': {'sms': False, 'email': bool(doc.client_email)}, 'reminder_enable': True,
        'notes': {'document_id': str(doc.pk), 'number': doc.number},
        'expire_by': int((timezone.now() + timedelta(days=30)).timestamp()),
    }
    res = _razorpay('POST', '/v1/payment_links', body)
    if not res.get('id') or not res.get('short_url'):
        raise BillingError('Razorpay did not return a payment link. Try again.')
    doc.razorpay_link_id, doc.razorpay_link_url, doc.razorpay_amount = res['id'], res['short_url'], amount
    doc.save(update_fields=['razorpay_link_id', 'razorpay_link_url', 'razorpay_amount', 'updated_at'])
    return doc


# ---------------------------------------------------------------------------
# Send on WhatsApp
# ---------------------------------------------------------------------------
def caption(doc, s):
    first = (doc.client_name or '').split(' ')[0] or 'there'
    if doc.doc_type == 'quote':
        return (f'Hi {first}! 📄 Here is your quotation *{doc.number}*' + (f' for *{doc.title}*' if doc.title else '') +
                f' from {s.business_name}.\nTotal: *{money(doc.total)}*' +
                (f' · valid until {doc.due_date:%d %b %Y}' if doc.due_date else '') +
                '\n\nTap *Accept quote* below (or reply ACCEPT) to go ahead, or ask us anything.')
    text = (f'Hi {first}! 🧾 Here is your invoice *{doc.number}*' + (f' for *{doc.title}*' if doc.title else '') +
            f'.\nAmount due: *{money(doc.balance)}*' + (f' · by {doc.due_date:%d %b %Y}' if doc.due_date else ''))
    if doc.razorpay_link_url:
        text += f'\n\nPay online (UPI / card / net banking): {doc.razorpay_link_url}'
    elif s.upi_id:
        text += f'\n\nUPI: {s.upi_id}'
    return text + '\n\nThank you! 🙏'


def template_line(doc, s):
    """The last value of the billing_document template (one line, no new lines)."""
    if doc.doc_type == 'quote':
        return 'Reply ACCEPT to go ahead, or ask us any question here.'
    if doc.razorpay_link_url:
        return f'Pay online: {doc.razorpay_link_url}'
    if s.upi_id:
        return f'Pay by UPI to {s.upi_id} and send the screenshot here.'
    return 'Payment details are in the PDF.'