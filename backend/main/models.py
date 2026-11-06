"""
Database models for the AJ Technologies admin dashboard.

These are the SAME Supabase tables the website uses. They are created by
supabase_schema.sql in Supabase, NOT by Django (managed = False), so there are
no migrations and `python manage.py migrate` is never needed.
"""
from datetime import date

from django.db import models


class ContactEnquiry(models.Model):
    """Quote requests sent from the website forms (or added by hand in the dashboard)."""

    TIMELINES = ('', 'asap', '1m', '3m', 'explore')
    CONTACT_METHODS = ('', 'whatsapp', 'call', 'email')
    SOURCES = ('home', 'contact', 'bot')      # bot = the WhatsApp bot (supabase_whatsapp.sql)
    VIAS = ('form', 'whatsapp', 'bot')
    LANGUAGES = ('en', 'ta')
    STATUSES = ('new', 'contacted', 'quoted', 'won', 'closed')

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30)
    email = models.CharField(max_length=254, blank=True, default='')
    business_name = models.CharField(max_length=160, blank=True, default='')
    services = models.JSONField(default=list, blank=True)
    timeline = models.CharField(max_length=10, blank=True, default='')
    contact_method = models.CharField(max_length=10, blank=True, default='')
    message = models.TextField(blank=True, default='')
    source = models.CharField(max_length=10, default='contact')
    submitted_via = models.CharField(max_length=10, default='form')
    language = models.CharField(max_length=2, default='en')
    status = models.CharField(max_length=10, default='new')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'contact_enquiries'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} · {self.phone}'

    def to_dict(self):
        return {
            'id': self.pk,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'business_name': self.business_name,
            'services': list(self.services or []),
            'timeline': self.timeline,
            'contact_method': self.contact_method,
            'message': self.message,
            'source': self.source,
            'submitted_via': self.submitted_via,
            'language': self.language,
            'status': self.status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class ShowcaseProject(models.Model):
    """Portfolio projects shown on the website."""

    CATEGORIES = ('web', 'shop', 'app', 'mkt')
    KINDS = ('site', 'app')

    id = models.BigAutoField(primary_key=True)
    title_en = models.CharField(max_length=150)
    title_ta = models.CharField(max_length=200, blank=True, default='')
    business_type_en = models.CharField(max_length=150)
    business_type_ta = models.CharField(max_length=200, blank=True, default='')
    built_en = models.TextField()
    built_ta = models.TextField(blank=True, default='')
    tags_en = models.JSONField(default=list, blank=True)
    tags_ta = models.JSONField(default=list, blank=True)
    category = models.CharField(max_length=10, default='web')
    kind = models.CharField(max_length=10, default='site')
    image_path = models.CharField(max_length=500, blank=True, default='')
    color_primary = models.CharField(max_length=7, default='#2563eb')
    color_secondary = models.CharField(max_length=7, default='#7c3aed')
    live_url = models.CharField(max_length=300, blank=True, default='')
    is_sample = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    show_on_home = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'showcase_projects'
        ordering = ['sort_order', '-created_at']

    def __str__(self):
        return self.title_en

    @property
    def image_is_in_bucket(self):
        """True when image_path points to a file in our Storage bucket (not an outside https:// link)."""
        path = (self.image_path or '').strip()
        return bool(path) and not path.startswith(('http://', 'https://'))

    def to_dict(self):
        return {
            'id': self.pk,
            'title_en': self.title_en,
            'title_ta': self.title_ta,
            'business_type_en': self.business_type_en,
            'business_type_ta': self.business_type_ta,
            'built_en': self.built_en,
            'built_ta': self.built_ta,
            'tags_en': list(self.tags_en or []),
            'tags_ta': list(self.tags_ta or []),
            'category': self.category,
            'kind': self.kind,
            'image_path': self.image_path,
            'color_primary': self.color_primary,
            'color_secondary': self.color_secondary,
            'live_url': self.live_url,
            'is_sample': self.is_sample,
            'is_published': self.is_published,
            'show_on_home': self.show_on_home,
            'sort_order': self.sort_order,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class ClientReview(models.Model):
    """Genuine client reviews shown in "What our clients say" on the website home page."""

    SOURCES = ('direct', 'google', 'whatsapp', 'email', 'website')

    id = models.BigAutoField(primary_key=True)
    client_name = models.CharField(max_length=120)
    business_name = models.CharField(max_length=160, blank=True, default='')
    location = models.CharField(max_length=120, blank=True, default='')
    rating = models.SmallIntegerField(default=5)
    review_en = models.TextField()
    review_ta = models.TextField(blank=True, default='')
    project_id = models.BigIntegerField(null=True, blank=True)
    source = models.CharField(max_length=10, default='direct')
    review_date = models.DateField(default=date.today)
    is_published = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'client_reviews'
        ordering = ['sort_order', '-review_date', '-created_at']

    def __str__(self):
        return f'{self.client_name} ({self.rating})'

    def to_dict(self):
        return {
            'id': self.pk,
            'client_name': self.client_name,
            'business_name': self.business_name,
            'location': self.location,
            'rating': self.rating,
            'review_en': self.review_en,
            'review_ta': self.review_ta,
            'project_id': self.project_id,
            'source': self.source,
            'review_date': self.review_date.isoformat(),
            'is_published': self.is_published,
            'sort_order': self.sort_order,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }



# ---------------------------------------------------------------------------
# WhatsApp bot tables (created by supabase_whatsapp.sql in the bot project)
# ---------------------------------------------------------------------------
def _iso(value):
    return value.isoformat() if value else None


class WaContact(models.Model):
    """One WhatsApp customer who has messaged the bot."""

    wa_id = models.CharField(max_length=20, primary_key=True)
    profile_name = models.CharField(max_length=120, blank=True, default='')
    name = models.CharField(max_length=120, blank=True, default='')
    business_name = models.CharField(max_length=160, blank=True, default='')
    email = models.CharField(max_length=254, blank=True, default='')
    language = models.CharField(max_length=12, default='en')
    language_locked = models.BooleanField(default=False)
    opted_out = models.BooleanField(default=False)
    opted_out_at = models.DateTimeField(null=True, blank=True)
    bot_enabled = models.BooleanField(default=True)
    needs_reply = models.BooleanField(default=False)
    unread_count = models.IntegerField(default=0)
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    last_outbound_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_preview = models.CharField(max_length=200, blank=True, default='')
    state = models.JSONField(default=dict, blank=True)
    nudged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'wa_contacts'

    def window_open(self, now):
        from datetime import timedelta
        return bool(self.last_inbound_at) and now - self.last_inbound_at < timedelta(hours=23, minutes=50)

    def to_dict(self, now):
        return {
            'wa_id': self.wa_id,
            'name': self.name,
            'profile_name': self.profile_name,
            'business_name': self.business_name,
            'email': self.email,
            'language': self.language,
            'opted_out': self.opted_out,
            'bot_enabled': self.bot_enabled,
            'needs_reply': self.needs_reply,
            'unread_count': self.unread_count,
            'flow': (self.state or {}).get('flow', ''),
            'window_open': self.window_open(now),
            'last_inbound_at': _iso(self.last_inbound_at),
            'last_message_at': _iso(self.last_message_at),
            'last_message_preview': self.last_message_preview,
            'created_at': _iso(self.created_at),
        }


class WaMessage(models.Model):
    """Every WhatsApp message in and out."""

    id = models.BigAutoField(primary_key=True)
    wa_id = models.CharField(max_length=20)
    direction = models.CharField(max_length=3)            # in / out
    sender = models.CharField(max_length=10)              # customer / bot / admin / system
    msg_type = models.CharField(max_length=20, default='text')
    body = models.TextField(blank=True, default='')
    media_id = models.CharField(max_length=100, blank=True, default='')
    media_mime = models.CharField(max_length=100, blank=True, default='')
    media_filename = models.CharField(max_length=200, blank=True, default='')
    wamid = models.CharField(max_length=200, null=True, blank=True)
    status = models.CharField(max_length=12, blank=True, default='')
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'wa_messages'

    def to_dict(self):
        return {
            'id': self.pk, 'direction': self.direction, 'sender': self.sender, 'type': self.msg_type,
            'body': self.body, 'media_id': self.media_id, 'media_mime': self.media_mime,
            'media_filename': self.media_filename, 'status': self.status, 'error': self.error,
            'created_at': _iso(self.created_at),
        }


class WaBooking(models.Model):
    """A call booked through the bot."""

    STATUSES = ('booked', 'done', 'missed', 'cancelled')

    id = models.BigAutoField(primary_key=True)
    wa_id = models.CharField(max_length=20, null=True, blank=True)
    name = models.CharField(max_length=120, blank=True, default='')
    phone = models.CharField(max_length=30, blank=True, default='')
    topic = models.CharField(max_length=500, blank=True, default='')
    call_date = models.DateField()
    call_time = models.TimeField()
    status = models.CharField(max_length=10, default='booked')
    enquiry_id = models.BigIntegerField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'wa_bookings'
        ordering = ['-call_date', '-call_time']

    def to_dict(self):
        return {
            'id': self.pk, 'wa_id': self.wa_id or '', 'name': self.name, 'phone': self.phone, 'topic': self.topic,
            'call_date': self.call_date.isoformat(), 'call_time': self.call_time.strftime('%H:%M'),
            'status': self.status, 'enquiry_id': self.enquiry_id, 'notes': self.notes,
            'created_at': _iso(self.created_at), 'updated_at': _iso(self.updated_at),
        }


class WaBroadcast(models.Model):
    """An offer broadcast (approved template sent to everyone who has not sent STOP)."""

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=120, blank=True, default='')
    template_name = models.CharField(max_length=512)
    template_language = models.CharField(max_length=15, default='en')
    body_preview = models.TextField(blank=True, default='')
    params = models.JSONField(default=list, blank=True)
    header_image_url = models.CharField(max_length=500, blank=True, default='')
    status = models.CharField(max_length=10, default='queued')
    total = models.IntegerField(default=0)
    sent = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'wa_broadcasts'
        ordering = ['-created_at']

    def to_dict(self):
        return {
            'id': self.pk, 'title': self.title, 'template_name': self.template_name,
            'template_language': self.template_language, 'body_preview': self.body_preview,
            'params': list(self.params or []), 'header_image_url': self.header_image_url, 'status': self.status,
            'total': self.total, 'sent': self.sent, 'failed': self.failed, 'created_at': _iso(self.created_at),
            'started_at': _iso(self.started_at), 'finished_at': _iso(self.finished_at),
        }


class WaBroadcastRecipient(models.Model):
    id = models.BigAutoField(primary_key=True)
    broadcast_id = models.BigIntegerField()
    wa_id = models.CharField(max_length=20)
    status = models.CharField(max_length=10, default='queued')
    error = models.TextField(blank=True, default='')
    wamid = models.CharField(max_length=200, blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'wa_broadcast_recipients'


# ---------------------------------------------------------------------------
# Upgrade v2 tables (created by supabase_upgrade_v2.sql in the bot project)
# ---------------------------------------------------------------------------
from django.contrib.postgres.fields import ArrayField  # noqa: E402


class ClientProject(models.Model):
    """A client's project. Its status is shown ONLY to the WhatsApp numbers in wa_ids."""

    STAGES = ('requirement', 'design', 'development', 'testing', 'launch', 'live', 'support', 'on_hold')

    id = models.BigAutoField(primary_key=True)
    client_name = models.CharField(max_length=120)
    business_name = models.CharField(max_length=160, blank=True, default='')
    wa_ids = ArrayField(models.CharField(max_length=20), size=3)
    title = models.CharField(max_length=160)
    service = models.CharField(max_length=80, blank=True, default='')
    stage = models.CharField(max_length=12, default='requirement')
    progress = models.SmallIntegerField(default=0)
    client_note = models.TextField(blank=True, default='')
    private_notes = models.TextField(blank=True, default='')
    live_url = models.CharField(max_length=300, blank=True, default='')
    start_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'client_projects'
        ordering = ['-updated_at']

    def to_dict(self):
        return {
            'id': self.pk, 'client_name': self.client_name, 'business_name': self.business_name,
            'wa_ids': list(self.wa_ids or []), 'title': self.title, 'service': self.service, 'stage': self.stage,
            'progress': self.progress, 'client_note': self.client_note, 'private_notes': self.private_notes,
            'live_url': self.live_url, 'start_date': self.start_date.isoformat() if self.start_date else '',
            'is_active': self.is_active, 'created_at': _iso(self.created_at), 'updated_at': _iso(self.updated_at),
        }


class ClientRenewal(models.Model):
    ITEMS = ('domain', 'hosting', 'ssl', 'amc', 'email', 'app_store', 'other')
    STATUSES = ('active', 'renewed', 'cancelled')

    id = models.BigAutoField(primary_key=True)
    project_id = models.BigIntegerField()
    item = models.CharField(max_length=10, default='domain')
    label = models.CharField(max_length=160, blank=True, default='')
    expiry_date = models.DateField()
    amount_text = models.CharField(max_length=60, blank=True, default='')
    auto_remind = models.BooleanField(default=True)
    status = models.CharField(max_length=10, default='active')
    reminded_30_at = models.DateTimeField(null=True, blank=True)
    reminded_7_at = models.DateTimeField(null=True, blank=True)
    reminded_1_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'client_renewals'
        ordering = ['expiry_date']

    def to_dict(self):
        return {
            'id': self.pk, 'project_id': self.project_id, 'item': self.item, 'label': self.label,
            'expiry_date': self.expiry_date.isoformat(), 'amount_text': self.amount_text,
            'auto_remind': self.auto_remind, 'status': self.status,
            'reminded': [d for d, v in (('30', self.reminded_30_at), ('7', self.reminded_7_at), ('1', self.reminded_1_at)) if v],
            'created_at': _iso(self.created_at), 'updated_at': _iso(self.updated_at),
        }


class SupportTicket(models.Model):
    STATUSES = ('open', 'in_progress', 'waiting', 'resolved', 'closed')
    PRIORITIES = ('normal', 'urgent')

    id = models.BigAutoField(primary_key=True)
    wa_id = models.CharField(max_length=20)
    project_id = models.BigIntegerField(null=True, blank=True)
    client_name = models.CharField(max_length=120, blank=True, default='')
    description = models.TextField()
    attachments = models.SmallIntegerField(default=0)
    priority = models.CharField(max_length=8, default='normal')
    status = models.CharField(max_length=12, default='open')
    client_update = models.TextField(blank=True, default='')
    private_notes = models.TextField(blank=True, default='')
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'support_tickets'
        ordering = ['-created_at']

    def to_dict(self):
        return {
            'id': self.pk, 'wa_id': self.wa_id, 'project_id': self.project_id, 'client_name': self.client_name,
            'description': self.description, 'attachments': self.attachments, 'priority': self.priority,
            'status': self.status, 'client_update': self.client_update, 'private_notes': self.private_notes,
            'resolved_at': _iso(self.resolved_at), 'created_at': _iso(self.created_at), 'updated_at': _iso(self.updated_at),
        }


class BotKnowledge(models.Model):
    KINDS = ('faq', 'info', 'offer')

    id = models.BigAutoField(primary_key=True)
    kind = models.CharField(max_length=8, default='faq')
    question = models.CharField(max_length=300, blank=True, default='')
    answer = models.TextField()
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'bot_knowledge'
        ordering = ['sort_order', 'id']

    def to_dict(self):
        return {'id': self.pk, 'kind': self.kind, 'question': self.question, 'answer': self.answer,
                'is_active': self.is_active, 'sort_order': self.sort_order,
                'created_at': _iso(self.created_at), 'updated_at': _iso(self.updated_at)}


class BotUnanswered(models.Model):
    id = models.BigAutoField(primary_key=True)
    wa_id = models.CharField(max_length=20, blank=True, default='')
    question = models.TextField()
    status = models.CharField(max_length=10, default='pending')
    knowledge_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'bot_unanswered'
        ordering = ['-created_at']

    def to_dict(self):
        return {'id': self.pk, 'wa_id': self.wa_id, 'question': self.question, 'status': self.status,
                'created_at': _iso(self.created_at)}

# ===========================================================================
# Upgrade v4 (tables from supabase_upgrade_v4.sql)
# ===========================================================================
def _num(value):
    return float(value or 0)


class BusinessSettings(models.Model):
    """One row (id = 1): your billing details, shown on every quotation / invoice PDF."""

    id = models.SmallIntegerField(primary_key=True, default=1)
    business_name = models.CharField(max_length=160, default='AJ Technologies')
    tagline = models.CharField(max_length=160, blank=True, default='')
    address = models.TextField(blank=True, default='')
    phone = models.CharField(max_length=40, blank=True, default='')
    email = models.CharField(max_length=254, blank=True, default='')
    website = models.CharField(max_length=200, blank=True, default='')
    upi_id = models.CharField(max_length=100, blank=True, default='')
    bank_details = models.TextField(blank=True, default='')
    quote_prefix = models.CharField(max_length=12, default='AJQ')
    invoice_prefix = models.CharField(max_length=12, default='AJINV')
    quote_valid_days = models.SmallIntegerField(default=15)
    invoice_due_days = models.SmallIntegerField(default=7)
    quote_terms = models.TextField(blank=True, default='')
    invoice_terms = models.TextField(blank=True, default='')
    footer_note = models.CharField(max_length=300, blank=True, default='')
    google_review_url = models.CharField(max_length=500, blank=True, default='')
    review_after_days = models.SmallIntegerField(default=3)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'business_settings'

    FIELDS = ('business_name', 'tagline', 'address', 'phone', 'email', 'website', 'upi_id', 'bank_details',
              'quote_prefix', 'invoice_prefix', 'quote_valid_days', 'invoice_due_days', 'quote_terms', 'invoice_terms',
              'footer_note', 'google_review_url', 'review_after_days')

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def to_dict(self):
        return {f: getattr(self, f) for f in self.FIELDS}


class BillingDocument(models.Model):
    """A quotation or an invoice."""

    TYPES = ('quote', 'invoice')
    STATUSES = ('draft', 'sent', 'accepted', 'rejected', 'expired', 'partly_paid', 'paid', 'cancelled')

    id = models.BigAutoField(primary_key=True)
    doc_type = models.CharField(max_length=8)
    number = models.CharField(max_length=40, unique=True)
    enquiry_id = models.BigIntegerField(null=True, blank=True)
    project_id = models.BigIntegerField(null=True, blank=True)
    converted_from = models.BigIntegerField(null=True, blank=True)
    client_name = models.CharField(max_length=120)
    business_name = models.CharField(max_length=160, blank=True, default='')
    client_wa_id = models.CharField(max_length=20, blank=True, default='')
    client_email = models.CharField(max_length=254, blank=True, default='')
    client_address = models.TextField(blank=True, default='')
    title = models.CharField(max_length=200, blank=True, default='')
    issue_date = models.DateField(default=date.today)
    due_date = models.DateField(null=True, blank=True)
    items = models.JSONField(default=list, blank=True)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=12, default='draft')
    notes = models.TextField(blank=True, default='')
    terms = models.TextField(blank=True, default='')
    private_notes = models.TextField(blank=True, default='')
    razorpay_link_id = models.CharField(max_length=60, blank=True, default='')
    razorpay_link_url = models.CharField(max_length=300, blank=True, default='')
    razorpay_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'billing_documents'
        ordering = ['-created_at']

    @property
    def subtotal(self):
        from decimal import Decimal
        return sum((Decimal(str(i.get('qty') or 0)) * Decimal(str(i.get('rate') or 0)) for i in self.items or []),
                   Decimal(0))

    @property
    def balance(self):
        return max(self.total - self.amount_paid, 0)

    def to_dict(self):
        return {
            'id': self.pk, 'doc_type': self.doc_type, 'number': self.number, 'enquiry_id': self.enquiry_id,
            'project_id': self.project_id, 'converted_from': self.converted_from, 'client_name': self.client_name,
            'business_name': self.business_name, 'client_wa_id': self.client_wa_id, 'client_email': self.client_email,
            'client_address': self.client_address, 'title': self.title, 'issue_date': self.issue_date.isoformat(),
            'due_date': self.due_date.isoformat() if self.due_date else '', 'items': list(self.items or []),
            'discount': _num(self.discount), 'subtotal': _num(self.subtotal), 'total': _num(self.total),
            'amount_paid': _num(self.amount_paid), 'balance': _num(self.balance), 'status': self.status,
            'notes': self.notes, 'terms': self.terms, 'private_notes': self.private_notes,
            'razorpay_link_url': self.razorpay_link_url, 'razorpay_amount': _num(self.razorpay_amount),
            'sent_at': _iso(self.sent_at), 'accepted_at': _iso(self.accepted_at), 'paid_at': _iso(self.paid_at),
            'created_at': _iso(self.created_at), 'updated_at': _iso(self.updated_at),
        }


class BillingPayment(models.Model):
    METHODS = ('razorpay', 'upi', 'bank', 'cash', 'cheque', 'other')

    id = models.BigAutoField(primary_key=True)
    document_id = models.BigIntegerField(null=True, blank=True)
    client_name = models.CharField(max_length=120, blank=True, default='')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=10, default='upi')
    paid_on = models.DateField(default=date.today)
    reference = models.CharField(max_length=120, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'billing_payments'
        ordering = ['-paid_on', '-id']

    def to_dict(self):
        return {'id': self.pk, 'document_id': self.document_id, 'client_name': self.client_name,
                'amount': _num(self.amount), 'method': self.method, 'paid_on': self.paid_on.isoformat(),
                'reference': self.reference, 'notes': self.notes, 'created_at': _iso(self.created_at)}


class BusinessExpense(models.Model):
    CATEGORIES = ('hosting', 'domain', 'software', 'ads', 'salary', 'freelancer', 'office', 'internet', 'travel', 'other')

    id = models.BigAutoField(primary_key=True)
    spent_on = models.DateField(default=date.today)
    category = models.CharField(max_length=20, default='other')
    description = models.CharField(max_length=300, blank=True, default='')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    project_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'business_expenses'
        ordering = ['-spent_on', '-id']

    def to_dict(self):
        return {'id': self.pk, 'spent_on': self.spent_on.isoformat(), 'category': self.category,
                'description': self.description, 'amount': _num(self.amount), 'project_id': self.project_id,
                'created_at': _iso(self.created_at)}


class MySubscription(models.Model):
    """AJ's own services (Render, Supabase, Meta, OpenAI, domain ...). Reminders are sent by the WhatsApp bot."""

    CYCLES = ('monthly', 'yearly', 'none')
    CHECKS = ('none', 'domain', 'ssl', 'meta_token', 'openai')

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=120)
    renews_on = models.DateField(null=True, blank=True)
    cycle = models.CharField(max_length=8, default='monthly')
    auto_renew = models.BooleanField(default=False)
    check_kind = models.CharField(max_length=12, default='none')
    check_target = models.CharField(max_length=300, blank=True, default='')
    amount_text = models.CharField(max_length=60, blank=True, default='')
    cost_inr = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_check_note = models.CharField(max_length=500, blank=True, default='')
    last_problem = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'my_subscriptions'
        ordering = ['renews_on', 'name']

    def to_dict(self):
        return {'id': self.pk, 'name': self.name, 'renews_on': self.renews_on.isoformat() if self.renews_on else '',
                'cycle': self.cycle, 'auto_renew': self.auto_renew, 'check_kind': self.check_kind,
                'check_target': self.check_target, 'amount_text': self.amount_text, 'cost_inr': _num(self.cost_inr),
                'notes': self.notes, 'is_active': self.is_active, 'last_checked_at': _iso(self.last_checked_at),
                'last_check_note': self.last_check_note, 'last_problem': self.last_problem,
                'updated_at': _iso(self.updated_at)}


class BlogPost(models.Model):
    id = models.BigAutoField(primary_key=True)
    slug = models.CharField(max_length=120, unique=True)
    title_en = models.CharField(max_length=200)
    title_ta = models.CharField(max_length=300, blank=True, default='')
    excerpt_en = models.CharField(max_length=400, blank=True, default='')
    excerpt_ta = models.CharField(max_length=600, blank=True, default='')
    body_en = models.TextField(blank=True, default='')
    body_ta = models.TextField(blank=True, default='')
    cover_image_path = models.CharField(max_length=500, blank=True, default='')
    tags = models.JSONField(default=list, blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'blog_posts'
        ordering = ['-published_at', '-created_at']

    def to_dict(self):
        return {'id': self.pk, 'slug': self.slug, 'title_en': self.title_en, 'title_ta': self.title_ta,
                'excerpt_en': self.excerpt_en, 'excerpt_ta': self.excerpt_ta, 'body_en': self.body_en,
                'body_ta': self.body_ta, 'cover_image_path': self.cover_image_path, 'tags': list(self.tags or []),
                'is_published': self.is_published, 'published_at': _iso(self.published_at),
                'created_at': _iso(self.created_at), 'updated_at': _iso(self.updated_at)}