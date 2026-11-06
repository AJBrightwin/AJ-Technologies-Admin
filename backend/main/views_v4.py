"""
Upgrade v4 API for the dashboard (tables from supabase_upgrade_v4.sql).

    Billing (quotations + invoices)
    GET/POST          /api/billing/docs/                     list / create            ?type=quote|invoice
    GET/PATCH/DELETE  /api/billing/docs/<id>/
    GET               /api/billing/docs/<id>/pdf/            the PDF (?download=1 to save it)
    POST              /api/billing/docs/<id>/send/           send the PDF to the client on WhatsApp
    POST              /api/billing/docs/<id>/convert/        quotation -> invoice
    POST              /api/billing/docs/<id>/link/           Razorpay payment link {amount}
    POST              /api/billing/docs/<id>/payments/       record a payment {amount, method, paid_on, reference, notes}
    GET               /api/billing/payments/                 all payments
    DELETE            /api/billing/payments/<id>/
    GET/PATCH         /api/billing/settings/                 billing details (name, address, UPI, bank, terms ...)

    Money
    GET               /api/money/?from=YYYY-MM-DD&to=YYYY-MM-DD   income, expenses, profit, outstanding, charts
    GET/POST          /api/money/expenses/
    PATCH/DELETE      /api/money/expenses/<id>/

    Your subscriptions (the WhatsApp bot reminds you every day at 12 PM before a renewal)
    GET/POST          /api/subscriptions/
    PATCH/DELETE      /api/subscriptions/<id>/
    POST              /api/subscriptions/<id>/renewed/       move to the next date

    Blog
    GET/POST          /api/blog/
    PATCH/DELETE      /api/blog/<id>/

    Extras on existing screens (they never break the old screens if the v4 SQL was not run yet)
    GET               /api/v4/extras/                        lead scores, case studies, review requests
    PATCH             /api/projects/<id>/case/               case study fields of a portfolio project
    POST              /api/clients/projects/<id>/review/     {ask_review} or {ask_now: true}
"""
import logging
import re
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.db import IntegrityError, ProgrammingError, connection, transaction
from django.http import HttpResponse
from django.utils import timezone

from . import billing, whatsapp
from .billing import D
from .models import (BillingDocument, BillingPayment, BlogPost, BusinessExpense, BusinessSettings, ClientProject,
                     ContactEnquiry, MySubscription, ShowcaseProject, WaContact)
from .views import (ApiError, _any_date, _bool, _choice, _clean, _email, _get, _json_body, _record_out, _save, _text,
                    _url, api, ok)

log = logging.getLogger(__name__)

NO_V4 = ('The new tables do not exist yet. In Supabase, open SQL Editor, run supabase_upgrade_v4.sql, '
         'then refresh this page.')
V4_TABLES = ('business_settings', 'billing_documents', 'billing_payments', 'business_expenses', 'blog_posts',
             'cost_inr', 'lead_score', 'lead_temp', 'case_study', 'went_live_at', 'ask_review', 'my_subscriptions')


def v4_guard(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ProgrammingError as e:
            if any(t in str(e) for t in V4_TABLES):
                raise ApiError(NO_V4, 503, code='no_table')
            raise
        except billing.BillingError as e:
            raise ApiError(str(e), 400, code='billing')
    return inner


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def _money(v, rule):
    try:
        d = Decimal(str(v if v not in (None, '') else 0))
    except Exception:
        raise ValueError('must be an amount like 15000')
    if d < 0 or d > Decimal('100000000'):
        raise ValueError('must be 0 or more')
    if rule.get('positive') and d <= 0:
        raise ValueError('must be more than 0')
    return D(d)


def _wa(v, rule):
    d = re.sub(r'\D', '', str(v or ''))
    if not d:
        return ''
    if len(d) == 10:
        d = '91' + d
    if len(d) == 11 and d.startswith('0'):
        d = '91' + d[1:]
    if not 10 <= len(d) <= 15:
        raise ValueError('enter a valid WhatsApp number with country code')
    return d


def _small(v, rule):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError('must be a whole number')
    if not rule['min'] <= n <= rule['max']:
        raise ValueError(f'{rule["min"]} to {rule["max"]}')
    return n


def _opt_id(v, rule):
    if v in (None, '', 0):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError('invalid')


def _items(v, rule):
    return billing.clean_items(v)


def _slug(v, rule):
    s = re.sub(r'[^a-z0-9]+', '-', str(v or '').lower()).strip('-')[:120]
    if rule.get('required') and not s:
        raise ValueError('required')
    return s


def _tags(v, rule):
    items = v if isinstance(v, list) else str(v or '').split(',')
    out = []
    for x in items:
        x = ' '.join(str(x).split())[:40]
        if x and x not in out:
            out.append(x)
    return out[:8]


DOC_FIELDS = {
    'client_name':    (_text,   {'max': 120, 'required': True}),
    'business_name':  (_text,   {'max': 160}),
    'client_wa_id':   (_wa,     {}),
    'client_email':   (_email,  {'max': 254}),
    'client_address': (_text,   {'max': 1000}),
    'title':          (_text,   {'max': 200}),
    'issue_date':     (_any_date, {}),
    'due_date':       (_any_date, {}),
    'items':          (_items,  {'required': True}),
    'discount':       (_money,  {}),
    'notes':          (_text,   {'max': 3000}),
    'terms':          (_text,   {'max': 3000}),
    'private_notes':  (_text,   {'max': 3000}),
    'enquiry_id':     (_opt_id, {}),
    'project_id':     (_opt_id, {}),
    'status':         (_choice, {'choices': BillingDocument.STATUSES}),
}

SETTINGS_FIELDS = {
    'business_name':     (_text, {'max': 160, 'required': True}),
    'tagline':           (_text, {'max': 160}),
    'address':           (_text, {'max': 600}),
    'phone':             (_text, {'max': 40}),
    'email':             (_email, {'max': 254}),
    'website':           (_url, {'max': 200}),
    'upi_id':            (_text, {'max': 100}),
    'bank_details':      (_text, {'max': 600}),
    'quote_prefix':      (_text, {'max': 12, 'required': True}),
    'invoice_prefix':    (_text, {'max': 12, 'required': True}),
    'quote_valid_days':  (_small, {'min': 1, 'max': 365}),
    'invoice_due_days':  (_small, {'min': 0, 'max': 365}),
    'quote_terms':       (_text, {'max': 3000}),
    'invoice_terms':     (_text, {'max': 3000}),
    'footer_note':       (_text, {'max': 300}),
    'google_review_url': (_url, {'max': 500}),
    'review_after_days': (_small, {'min': 0, 'max': 60}),
}

PAYMENT_FIELDS = {
    'amount':    (_money, {'positive': True, 'required': True}),
    'method':    (_choice, {'choices': BillingPayment.METHODS}),
    'paid_on':   (_any_date, {}),
    'reference': (_text, {'max': 120}),
    'notes':     (_text, {'max': 1000}),
}

EXPENSE_FIELDS = {
    'spent_on':    (_any_date, {'required': True}),
    'category':    (_choice, {'choices': BusinessExpense.CATEGORIES}),
    'description': (_text, {'max': 300}),
    'amount':      (_money, {'positive': True, 'required': True}),
    'project_id':  (_opt_id, {}),
}

SUB_FIELDS = {
    'name':         (_text, {'max': 120, 'required': True}),
    'renews_on':    (_any_date, {}),
    'cycle':        (_choice, {'choices': MySubscription.CYCLES}),
    'auto_renew':   (_bool, {}),
    'check_kind':   (_choice, {'choices': MySubscription.CHECKS}),
    'check_target': (_text, {'max': 300}),
    'amount_text':  (_text, {'max': 60}),
    'cost_inr':     (_money, {}),
    'notes':        (_text, {'max': 2000}),
    'is_active':    (_bool, {}),
}

BLOG_FIELDS = {
    'slug':             (_slug, {'required': True}),
    'title_en':         (_text, {'max': 200, 'required': True}),
    'title_ta':         (_text, {'max': 300}),
    'excerpt_en':       (_text, {'max': 400}),
    'excerpt_ta':       (_text, {'max': 600}),
    'body_en':          (_text, {'max': 60000}),
    'body_ta':          (_text, {'max': 80000}),
    'cover_image_path': (_text, {'max': 500}),
    'tags':             (_tags, {}),
    'is_published':     (_bool, {}),
}

CASE_FIELDS = {
    'slug':          (_slug, {}),
    'case_study':    (_bool, {}),
    'challenge_en':  (_text, {'max': 4000}), 'challenge_ta': (_text, {'max': 6000}),
    'solution_en':   (_text, {'max': 4000}), 'solution_ta':  (_text, {'max': 6000}),
    'results_en':    (_text, {'max': 4000}), 'results_ta':   (_text, {'max': 6000}),
    'tech_used':     (_tags, {}),
    'duration_text': (_text, {'max': 60}),
}


# ===========================================================================
# Billing
# ===========================================================================
def _recalc(doc):
    """amount_paid + status from the payments."""
    paid = sum((p.amount for p in BillingPayment.objects.filter(document_id=doc.pk)), Decimal(0))
    doc.amount_paid = D(paid)
    if doc.doc_type == 'invoice' and doc.status != 'cancelled':
        if paid >= doc.total and doc.total > 0:
            doc.status = 'paid'
            doc.paid_at = doc.paid_at or timezone.now()
        elif paid > 0:
            doc.status, doc.paid_at = 'partly_paid', None
        elif doc.status in ('paid', 'partly_paid'):
            doc.status, doc.paid_at = ('sent' if doc.sent_at else 'draft'), None
    doc.save(update_fields=['amount_paid', 'status', 'paid_at', 'updated_at'])
    return doc


def _defaults(doc_type, s):
    today = billing.ist_today()
    days = s.quote_valid_days if doc_type == 'quote' else s.invoice_due_days
    return today, today + timedelta(days=days)


@api(['GET', 'POST'])
@v4_guard
def billing_docs(request):
    if request.method == 'GET':
        qs = BillingDocument.objects.all()
        kind = request.GET.get('type')
        if kind in BillingDocument.TYPES:
            qs = qs.filter(doc_type=kind)
        return ok(items=[d.to_dict() for d in qs[:1000]], razorpay=billing.razorpay_ready(),
                  whatsapp=whatsapp.is_configured())
    data = _json_body(request)
    doc_type = data.get('doc_type')
    if doc_type not in BillingDocument.TYPES:
        raise ApiError('Choose quotation or invoice.')
    values = _clean(DOC_FIELDS, data, partial=False)
    values.pop('status', None)
    s = BusinessSettings.load()
    issue, due = _defaults(doc_type, s)
    values.setdefault('issue_date', None)
    values['issue_date'] = values['issue_date'] or issue
    if 'due_date' not in data:
        values['due_date'] = due
    try:
        values['total'] = billing.compute_total(values['items'], values.get('discount', 0))
    except ValueError as e:
        raise ApiError('Please fix the highlighted fields.', 400, errors={'discount': str(e)})
    if not values.get('terms'):
        values['terms'] = s.quote_terms if doc_type == 'quote' else s.invoice_terms
    for attempt in range(5):
        try:
            with transaction.atomic():
                doc = BillingDocument.objects.create(doc_type=doc_type, number=billing.next_number(doc_type, s),
                                                     status='draft', **values)
            break
        except IntegrityError:
            if attempt == 4:
                raise ApiError('Could not create a new number. Please try again.')
    log.info('%s %s created', doc_type, doc.number)
    return ok(201, item=doc.to_dict())


@api(['GET', 'PATCH', 'DELETE'])
@v4_guard
def billing_doc(request, pk):
    doc = _get(BillingDocument, pk)
    if request.method == 'GET':
        return ok(item=doc.to_dict(), payments=[p.to_dict() for p in BillingPayment.objects.filter(document_id=pk)])
    if request.method == 'DELETE':
        if BillingPayment.objects.filter(document_id=pk).exists():
            raise ApiError('This invoice has payments. Delete the payments first, or mark it Cancelled instead.')
        doc.delete()
        return ok()
    data = _json_body(request)
    values = _clean(DOC_FIELDS, data, partial=True)
    if 'items' in values or 'discount' in values:
        items = values.get('items', doc.items)
        try:
            values['total'] = billing.compute_total(items, values.get('discount', doc.discount))
        except ValueError as e:
            raise ApiError('Please fix the highlighted fields.', 400, errors={'discount': str(e)})
        if values['total'] < doc.amount_paid:
            raise ApiError(f'The new total is less than what was already paid ({billing.money(doc.amount_paid)}).')
    st = values.get('status')
    if st:
        if doc.doc_type == 'quote' and st in ('partly_paid', 'paid'):
            raise ApiError('A quotation cannot be paid. Convert it to an invoice first.')
        if doc.doc_type == 'invoice' and st in ('accepted', 'rejected', 'expired'):
            raise ApiError('That status is only for quotations.')
        if st == 'accepted' and not doc.accepted_at:
            values['accepted_at'] = timezone.now()
        if st == 'sent' and not doc.sent_at:
            values['sent_at'] = timezone.now()
    if values:
        _save(doc, values)
    if 'total' in values and doc.doc_type == 'invoice':
        _recalc(doc)
    return ok(item=doc.to_dict())


@api(['GET'])
@v4_guard
def billing_pdf(request, pk):
    doc = _get(BillingDocument, pk)
    data = billing.pdf(doc, BusinessSettings.load())
    res = HttpResponse(data, content_type='application/pdf')
    how = 'attachment' if request.GET.get('download') else 'inline'
    res['Content-Disposition'] = f'{how}; filename="{billing.filename(doc)}"'
    return res


@api(['POST'])
@v4_guard
def billing_send(request, pk):
    doc = _get(BillingDocument, pk)
    if not doc.client_wa_id:
        raise ApiError('Add the client\'s WhatsApp number first (Edit).', 400, errors={'client_wa_id': 'required'})
    if doc.status == 'cancelled':
        raise ApiError('This document is cancelled.')
    s = BusinessSettings.load()
    if doc.doc_type == 'invoice' and not doc.razorpay_link_url and billing.razorpay_ready() and doc.balance > 0 \
            and _json_body(request).get('with_link', True):
        billing.create_payment_link(doc)
    if doc.status == 'draft':
        doc.status = 'sent'                     # the PDF the client gets has no DRAFT mark (saved below)
    data = billing.pdf(doc, s)
    name = billing.filename(doc)
    media_id = whatsapp.upload_media(data, 'application/pdf', name)
    contact, _ = WaContact.objects.get_or_create(pk=doc.client_wa_id, defaults={'name': doc.client_name[:120]})
    text = billing.caption(doc, s)
    if contact.window_open(timezone.now()):
        wamid = whatsapp.send(doc.client_wa_id, whatsapp.document_payload(media_id, name, text))
        _record_out(contact, 'admin', 'document', f'📎 {name}\n{text}', wamid, clear=False)
        via = 'message'
        if doc.doc_type == 'quote':
            body = 'Would you like to go ahead with this quotation?'
            wamid = whatsapp.send(doc.client_wa_id, whatsapp.buttons_payload(
                body, [(f'qt:accept:{doc.pk}', '✅ Accept quote'), (f'qt:ask:{doc.pk}', '💬 Ask a question')]))
            _record_out(contact, 'admin', 'interactive', body, wamid, clear=False)
    else:
        first = (doc.client_name or '').split(' ')[0] or 'there'
        kind = 'quotation' if doc.doc_type == 'quote' else 'invoice'
        amount = billing.money(doc.total if doc.doc_type == 'quote' else doc.balance)
        params = [first, kind, doc.number, amount, billing.template_line(doc, s)]
        wamid = whatsapp.send(doc.client_wa_id, whatsapp.document_template_payload(
            settings.TPL_BILLING_DOCUMENT, settings.TPL_LANG, media_id, name, params))
        _record_out(contact, 'admin', 'template',
                    f'[Template {settings.TPL_BILLING_DOCUMENT}] 📎 {name} · {kind} {doc.number} · {amount}', wamid, clear=False)
        via = 'template'
    _save(doc, {'sent_at': timezone.now(), 'status': doc.status})
    if doc.doc_type == 'quote' and doc.enquiry_id:
        ContactEnquiry.objects.filter(pk=doc.enquiry_id, status__in=('new', 'contacted')).update(status='quoted')
    return ok(item=doc.to_dict(), via=via)


@api(['POST'])
@v4_guard
def billing_convert(request, pk):
    quote = _get(BillingDocument, pk)
    if quote.doc_type != 'quote':
        raise ApiError('Only a quotation can be converted.')
    data = _json_body(request)
    s = BusinessSettings.load()
    items = quote.items
    pct = data.get('advance_percent')
    if pct not in (None, '', 100):
        try:
            pct = Decimal(str(pct))
            assert 0 < pct < 100
        except Exception:
            raise ApiError('Advance must be between 1 and 99 %.')
        amount = D(quote.total * pct / 100)
        items = [{'description': f'Advance payment ({pct.normalize():f}%) for {quote.title or quote.number}',
                  'details': f'As per quotation {quote.number} (total {billing.money(quote.total)})',
                  'qty': 1, 'rate': float(amount)}]
        total, discount = amount, Decimal(0)
    else:
        total, discount = quote.total, quote.discount
    issue, due = _defaults('invoice', s)
    for attempt in range(5):
        try:
            with transaction.atomic():
                inv = BillingDocument.objects.create(
                    doc_type='invoice', number=billing.next_number('invoice', s), enquiry_id=quote.enquiry_id,
                    project_id=quote.project_id, converted_from=quote.pk, client_name=quote.client_name,
                    business_name=quote.business_name, client_wa_id=quote.client_wa_id, client_email=quote.client_email,
                    client_address=quote.client_address, title=quote.title, issue_date=issue, due_date=due, items=items,
                    discount=discount, total=total, status='draft', notes=quote.notes, terms=s.invoice_terms)
            break
        except IntegrityError:
            if attempt == 4:
                raise ApiError('Could not create a new number. Please try again.')
    if quote.status in ('draft', 'sent'):
        _save(quote, {'status': 'accepted', 'accepted_at': quote.accepted_at or timezone.now()})
    if quote.enquiry_id:
        ContactEnquiry.objects.filter(pk=quote.enquiry_id).exclude(status='won').update(status='won')
    return ok(201, item=inv.to_dict(), quote=quote.to_dict())


@api(['POST'])
@v4_guard
def billing_link(request, pk):
    doc = _get(BillingDocument, pk)
    if doc.doc_type != 'invoice':
        raise ApiError('Payment links are for invoices. Convert the quotation to an invoice first.')
    if doc.status in ('paid', 'cancelled'):
        raise ApiError('This invoice is already ' + doc.status + '.')
    amount = _json_body(request).get('amount')
    billing.create_payment_link(doc, amount)
    return ok(item=doc.to_dict())


@api(['POST'])
@v4_guard
def billing_add_payment(request, pk):
    doc = _get(BillingDocument, pk)
    if doc.doc_type != 'invoice':
        raise ApiError('Record payments on an invoice (convert the quotation first).')
    values = _clean(PAYMENT_FIELDS, _json_body(request), partial=False)
    values['paid_on'] = values.get('paid_on') or billing.ist_today()
    if values['amount'] > doc.balance:
        raise ApiError(f'More than the balance ({billing.money(doc.balance)}).', 400, errors={'amount': 'too much'})
    BillingPayment.objects.create(document_id=doc.pk, client_name=doc.client_name, **values)
    _recalc(doc)
    return ok(201, item=doc.to_dict(), payments=[p.to_dict() for p in BillingPayment.objects.filter(document_id=pk)])


@api(['GET'])
@v4_guard
def billing_payments(request):
    docs = {d['id']: d for d in BillingDocument.objects.values('id', 'number', 'title')}
    items = []
    for p in BillingPayment.objects.all()[:1000]:
        d = p.to_dict()
        doc = docs.get(p.document_id)
        d['number'], d['title'] = (doc['number'], doc['title']) if doc else ('', '')
        items.append(d)
    return ok(items=items)


@api(['DELETE'])
@v4_guard
def billing_payment(request, pk):
    p = _get(BillingPayment, pk)
    doc_id = p.document_id
    p.delete()
    doc = BillingDocument.objects.filter(pk=doc_id).first()
    if doc:
        _recalc(doc)
    return ok(item=doc.to_dict() if doc else None)


@api(['GET', 'PATCH'])
@v4_guard
def billing_settings(request):
    s = BusinessSettings.load()
    if request.method == 'PATCH':
        values = _clean(SETTINGS_FIELDS, _json_body(request), partial=True)
        for k in ('quote_prefix', 'invoice_prefix'):
            if k in values:
                values[k] = re.sub(r'[^A-Za-z0-9]', '', values[k]).upper()[:10]
                if not values[k]:
                    raise ApiError('Please fix the highlighted fields.', 400, errors={k: 'letters / numbers only'})
        if values:
            _save(s, values)
    return ok(item=s.to_dict(), razorpay=billing.razorpay_ready(),
              webhook_url='https://bot.ajtechnologiesltd.com/razorpay/webhook')


# ===========================================================================
# Money: income & profit
# ===========================================================================
def _period(request):
    today = billing.ist_today()
    try:
        start = date.fromisoformat(request.GET.get('from') or '')
    except ValueError:
        start = today.replace(day=1)
    try:
        end = date.fromisoformat(request.GET.get('to') or '')
    except ValueError:
        end = today
    if start > end:
        start, end = end, start
    return start, end


@api(['GET'])
@v4_guard
def money(request):
    start, end = _period(request)
    out = {'from': start.isoformat(), 'to': end.isoformat()}
    with connection.cursor() as cur:
        cur.execute('SELECT COALESCE(sum(amount), 0), count(*) FROM billing_payments WHERE paid_on BETWEEN %s AND %s',
                    [start, end])
        income, n_pay = cur.fetchone()
        cur.execute('SELECT COALESCE(sum(amount), 0) FROM business_expenses WHERE spent_on BETWEEN %s AND %s', [start, end])
        spent = cur.fetchone()[0]
        cur.execute("""SELECT COALESCE(sum(total - amount_paid), 0), count(*),
                              COALESCE(sum(total - amount_paid) FILTER (WHERE due_date < (now() AT TIME ZONE 'Asia/Kolkata')::date), 0),
                              count(*) FILTER (WHERE due_date < (now() AT TIME ZONE 'Asia/Kolkata')::date)
                       FROM billing_documents WHERE doc_type = 'invoice' AND status IN ('sent', 'partly_paid')""")
        outstanding, n_out, overdue, n_overdue = cur.fetchone()
        cur.execute("""SELECT COALESCE(sum(total), 0), count(*) FROM billing_documents
                       WHERE doc_type = 'quote' AND status = 'sent'""")
        quoted, n_quoted = cur.fetchone()
        cur.execute("""SELECT count(*) FILTER (WHERE status IN ('accepted', 'paid', 'partly_paid')), count(*)
                       FROM billing_documents WHERE doc_type = 'quote' AND issue_date BETWEEN %s AND %s
                         AND status NOT IN ('draft', 'cancelled')""", [start, end])
        q_won, q_all = cur.fetchone()
        cur.execute("""SELECT COALESCE(sum(CASE cycle WHEN 'monthly' THEN cost_inr WHEN 'yearly' THEN cost_inr / 12 ELSE 0 END), 0)
                       FROM my_subscriptions WHERE is_active""")
        subs_month = cur.fetchone()[0]
        # last 12 months (India time)
        cur.execute("""WITH m AS (SELECT generate_series(date_trunc('month', (now() AT TIME ZONE 'Asia/Kolkata')::date) - interval '11 months',
                                                         date_trunc('month', (now() AT TIME ZONE 'Asia/Kolkata')::date), interval '1 month')::date AS m)
                       SELECT m.m,
                              (SELECT COALESCE(sum(amount), 0) FROM billing_payments WHERE date_trunc('month', paid_on) = m.m),
                              (SELECT COALESCE(sum(amount), 0) FROM business_expenses WHERE date_trunc('month', spent_on) = m.m)
                       FROM m ORDER BY m.m""")
        months = [{'month': m.isoformat()[:7], 'income': float(i), 'expenses': float(e)} for m, i, e in cur.fetchall()]
        cur.execute("""SELECT method, sum(amount) FROM billing_payments WHERE paid_on BETWEEN %s AND %s
                       GROUP BY method ORDER BY 2 DESC""", [start, end])
        by_method = [{'name': m, 'amount': float(a)} for m, a in cur.fetchall()]
        cur.execute("""SELECT category, sum(amount) FROM business_expenses WHERE spent_on BETWEEN %s AND %s
                       GROUP BY category ORDER BY 2 DESC""", [start, end])
        by_category = [{'name': c, 'amount': float(a)} for c, a in cur.fetchall()]
        cur.execute("""SELECT COALESCE(NULLIF(client_name, ''), 'Unknown'), sum(amount) FROM billing_payments
                       WHERE paid_on BETWEEN %s AND %s GROUP BY 1 ORDER BY 2 DESC LIMIT 6""", [start, end])
        top = [{'name': c, 'amount': float(a)} for c, a in cur.fetchall()]
        cur.execute("""SELECT id, number, client_name, title, total - amount_paid, due_date, client_wa_id
                       FROM billing_documents WHERE doc_type = 'invoice' AND status IN ('sent', 'partly_paid')
                       ORDER BY due_date NULLS LAST LIMIT 20""")
        unpaid = [{'id': r[0], 'number': r[1], 'client_name': r[2], 'title': r[3], 'balance': float(r[4]),
                   'due_date': r[5].isoformat() if r[5] else '', 'client_wa_id': r[6]} for r in cur.fetchall()]
    out.update(income=float(income), payments=n_pay, expenses=float(spent), profit=float(income - spent),
               margin=round(float((income - spent) / income * 100)) if income else None,
               outstanding=float(outstanding), outstanding_count=n_out, overdue=float(overdue), overdue_count=n_overdue,
               quoted=float(quoted), quoted_count=n_quoted, quote_win=round(q_won / q_all * 100) if q_all else None,
               subs_month=float(subs_month), months=months, by_method=by_method, by_category=by_category,
               top_clients=top, unpaid=unpaid)
    return ok(**out)


@api(['GET', 'POST'])
@v4_guard
def expenses(request):
    if request.method == 'GET':
        start, end = _period(request) if request.GET.get('from') else (date(2000, 1, 1), date(2100, 1, 1))
        return ok(items=[e.to_dict() for e in BusinessExpense.objects.filter(spent_on__range=(start, end))[:2000]])
    values = _clean(EXPENSE_FIELDS, _json_body(request), partial=False)
    item = BusinessExpense.objects.create(**values)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
@v4_guard
def expense(request, pk):
    item = _get(BusinessExpense, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(EXPENSE_FIELDS, _json_body(request), partial=True)
    if values:
        for k, v in values.items():
            setattr(item, k, v)
        item.save(update_fields=list(values))
    return ok(item=item.to_dict())


# ===========================================================================
# Your subscriptions
# ===========================================================================
def _next_date(d, cycle):
    if not d or cycle == 'none':
        return d
    months = 1 if cycle == 'monthly' else 12
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@api(['GET', 'POST'])
@v4_guard
def subscriptions(request):
    if request.method == 'GET':
        return ok(items=[s.to_dict() for s in MySubscription.objects.all()],
                  alert_at='12:00 PM', alert_days=7)
    values = _clean(SUB_FIELDS, _json_body(request), partial=False)
    item = MySubscription.objects.create(**values)
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
@v4_guard
def subscription(request, pk):
    item = _get(MySubscription, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(SUB_FIELDS, _json_body(request), partial=True)
    if values:
        _save(item, values)
    return ok(item=item.to_dict())


@api(['POST'])
@v4_guard
def subscription_renewed(request, pk):
    item = _get(MySubscription, pk)
    nxt = _json_body(request).get('next_date')
    if nxt:
        try:
            new = date.fromisoformat(nxt)
        except ValueError:
            raise ApiError('Use a date like 2027-01-15.')
    else:
        if not item.renews_on or item.cycle == 'none':
            raise ApiError('Set the next renewal date for this one.')
        new = item.renews_on
        today = billing.ist_today()
        while new <= today or new == item.renews_on:
            new = _next_date(new, item.cycle)
    _save(item, {'renews_on': new, 'last_problem': ''})
    return ok(item=item.to_dict())


# ===========================================================================
# Blog
# ===========================================================================
@api(['GET', 'POST'])
@v4_guard
def blog(request):
    if request.method == 'GET':
        return ok(items=[b.to_dict() for b in BlogPost.objects.all()], site=settings.SITE_URL)
    values = _clean(BLOG_FIELDS, _json_body(request), partial=False)
    if values.get('is_published'):
        values['published_at'] = timezone.now()
    try:
        with transaction.atomic():
            item = BlogPost.objects.create(**values)
    except IntegrityError:
        raise ApiError('Please fix the highlighted fields.', 400, errors={'slug': 'another post uses this link'})
    return ok(201, item=item.to_dict())


@api(['PATCH', 'DELETE'])
@v4_guard
def blog_post(request, pk):
    item = _get(BlogPost, pk)
    if request.method == 'DELETE':
        item.delete()
        return ok()
    values = _clean(BLOG_FIELDS, _json_body(request), partial=True)
    if values.get('is_published') and not item.published_at:
        values['published_at'] = timezone.now()
    try:
        with transaction.atomic():
            if values:
                _save(item, values)
    except IntegrityError:
        raise ApiError('Please fix the highlighted fields.', 400, errors={'slug': 'another post uses this link'})
    return ok(item=item.to_dict())


# ===========================================================================
# Extras on the old screens (raw SQL, so the old screens keep working before the v4 SQL is run)
# ===========================================================================
@api(['GET'])
def extras(request):
    out = {'ready': True, 'leads': {}, 'cases': {}, 'reviews': {}}
    try:
        with connection.cursor() as cur:
            cur.execute("""SELECT id, lead_score, lead_temp, lead_reason FROM contact_enquiries
                           WHERE lead_temp <> '' ORDER BY id DESC LIMIT 3000""")
            out['leads'] = {r[0]: {'score': r[1], 'temp': r[2], 'reason': r[3]} for r in cur.fetchall()}
            cur.execute("""SELECT id, slug, case_study, challenge_en, challenge_ta, solution_en, solution_ta, results_en,
                                  results_ta, tech_used, duration_text FROM showcase_projects""")
            cols = ['slug', 'case_study', 'challenge_en', 'challenge_ta', 'solution_en', 'solution_ta', 'results_en',
                    'results_ta', 'tech_used', 'duration_text']
            out['cases'] = {r[0]: dict(zip(cols, r[1:])) for r in cur.fetchall()}
            cur.execute("""SELECT id, went_live_at, review_requested_at, review_rating, ask_review FROM client_projects""")
            out['reviews'] = {r[0]: {'went_live_at': r[1].isoformat() if r[1] else None,
                                     'review_requested_at': r[2].isoformat() if r[2] else None,
                                     'review_rating': r[3], 'ask_review': r[4]} for r in cur.fetchall()}
            cur.execute('SELECT review_after_days, google_review_url FROM business_settings WHERE id = 1')
            row = cur.fetchone()
            out['review_after_days'], out['google_review_url'] = (row[0], row[1]) if row else (3, '')
    except ProgrammingError:
        out['ready'] = False
    for v in out['cases'].values():
        if isinstance(v.get('tech_used'), str):
            import json
            v['tech_used'] = json.loads(v['tech_used'] or '[]')
    return ok(**out)


@api(['PATCH'])
@v4_guard
def project_case(request, pk):
    _get(ShowcaseProject, pk)
    values = _clean(CASE_FIELDS, _json_body(request), partial=True)
    if values.get('case_study') and not values.get('slug'):
        with connection.cursor() as cur:
            cur.execute('SELECT slug, title_en FROM showcase_projects WHERE id = %s', [pk])
            slug, title = cur.fetchone()
        if not slug:
            values['slug'] = _slug(title, {})
    if not values:
        return ok()
    import json
    sets, params = [], []
    for k, v in values.items():
        sets.append(f'{k} = %s')
        params.append(json.dumps(v) if k == 'tech_used' else v)
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"UPDATE showcase_projects SET {', '.join(sets)} WHERE id = %s", params + [pk])
    except IntegrityError:
        raise ApiError('Please fix the highlighted fields.', 400, errors={'slug': 'another project uses this link'})
    return ok(values={k: v for k, v in values.items()})


@api(['POST'])
@v4_guard
def client_project_review(request, pk):
    p = _get(ClientProject, pk)
    data = _json_body(request)
    with connection.cursor() as cur:
        if data.get('ask_now') is True:
            if p.stage not in ('live', 'support'):
                raise ApiError('Set the project stage to Live first.')
            cur.execute("""UPDATE client_projects SET ask_review = true, review_requested_at = NULL,
                               went_live_at = now() - make_interval(days => COALESCE(
                                   (SELECT review_after_days FROM business_settings WHERE id = 1), 3) + 1)
                           WHERE id = %s""", [pk])
        elif isinstance(data.get('ask_review'), bool):
            cur.execute('UPDATE client_projects SET ask_review = %s WHERE id = %s', [data['ask_review'], pk])
        else:
            raise ApiError('Nothing to change.')
    return ok()