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
    SOURCES = ('home', 'contact')
    VIAS = ('form', 'whatsapp')
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