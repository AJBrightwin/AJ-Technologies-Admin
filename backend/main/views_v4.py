"""
Upgrade v4 pages:

    /areas-we-serve/                         every service x place page, grouped by region
    /<service>-in-<place>/                   e.g. /website-development-in-thoothukudi/ (80 pages for Google)
    /blog/  and  /blog/<slug>/               posts written in the dashboard
    /portfolio/<slug>/                       case study of a portfolio project (switched on in the dashboard)
    /sitemap.xml                             built automatically (pages, places, posts, case studies)

Every database read is wrapped, so a page never breaks if the database is briefly unreachable or
supabase_upgrade_v4.sql has not been run yet (blog / case studies are then simply empty).
"""
import json
import logging
from datetime import date

from django.db import connection
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from . import markdown_lite, seo_data
from .models import BlogPost, ClientReview, ShowcaseProject, storage_url

log = logging.getLogger(__name__)
SITE = seo_data.SITE
ORG = {'@type': 'Organization', 'name': 'AJ Technologies', 'url': SITE + '/',
       'logo': SITE + '/static/images/logo-icon.png', 'telephone': '+91-90926-31501',
       'email': 'ajtechnologieslimited@gmail.com',
       'address': {'@type': 'PostalAddress', 'addressLocality': 'Thoothukudi', 'addressRegion': 'Tamil Nadu',
                   'addressCountry': 'IN'},
       'sameAs': ['https://www.instagram.com/aj_technologies_ltd_/', 'https://www.youtube.com/@AJ_Technologies']}


def _crumbs(*items):
    return {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': i, 'name': name, 'item': SITE + url} for i, (name, url) in enumerate(items, 1)]}


# ===========================================================================
# R. Service x place pages
# ===========================================================================
def _faqs(s, c):
    city, city_in, svc, svc_ta = c['en'], c['ta_in'], s['en'].lower(), s['ta']
    here = c['region'] == 'home'
    return [
        {'q_en': f'How much does {svc} cost in {city}?',
         'q_ta': f'{city_in} {svc_ta} எவ்வளவு செலவாகும்?',
         'a_en': 'Every project is different, so we never use a fixed price list. Tell us what you need on WhatsApp and we send '
                 'a clear, written quotation within 24 hours, free and with no obligation.',
         'a_ta': 'ஒவ்வொரு திட்டமும் வேறுபட்டது, அதனால் நிலையான விலைப் பட்டியல் இல்லை. உங்கள் தேவையை WhatsApp-ல் சொல்லுங்கள்; '
                 '24 மணி நேரத்தில் தெளிவான எழுத்துப்பூர்வ மதிப்பீட்டை இலவசமாக அனுப்புவோம்.'},
        {'q_en': f'Do you work with businesses in {city}?' if c['region'] not in ('state', 'india') else f'Do you work with businesses all over {city}?',
         'q_ta': f'{city_in} உள்ள வணிகங்களுக்கும் வேலை செய்கிறீர்களா?',
         'a_en': ('Yes. We are based in Thoothukudi district, so we can meet you in person when needed, and we stay in touch on '
                  'WhatsApp and phone every step of the way.') if here else
                 ('Yes. We work with clients across Tamil Nadu and India online: WhatsApp, phone and video calls, with a shared '
                  'progress update at every stage. You never need to travel.'),
         'a_ta': ('ஆம். நாங்கள் தூத்துக்குடி மாவட்டத்தில் இருப்பதால் தேவைப்பட்டால் நேரில் சந்திக்கலாம்; ஒவ்வொரு படியிலும் '
                  'WhatsApp, போன் மூலம் தொடர்பில் இருப்போம்.') if here else
                 ('ஆம். தமிழ்நாடு மற்றும் இந்தியா முழுவதும் உள்ள வாடிக்கையாளர்களுடன் WhatsApp, போன், வீடியோ அழைப்பு மூலம் ஆன்லைனில் '
                  'வேலை செய்கிறோம். ஒவ்வொரு கட்டத்திலும் முன்னேற்றத்தைப் பகிர்வோம்; நீங்கள் பயணிக்க வேண்டியதில்லை.')},
        {'q_en': f'How long does {svc} take?', 'q_ta': f'{svc_ta} எவ்வளவு நாட்கள் ஆகும்?',
         'a_en': 'Most business websites go live in 1 to 3 weeks; online stores and apps take longer depending on the features. '
                 'You get the exact timeline with your quotation, and live progress updates on WhatsApp.',
         'a_ta': 'பெரும்பாலான வணிக இணையதளங்கள் 1 முதல் 3 வாரங்களில் தயாராகும்; ஆன்லைன் ஸ்டோர், ஆப்ஸ் அம்சங்களைப் பொறுத்து '
                 'சற்று அதிக நாட்கள் ஆகும். சரியான கால அட்டவணை மதிப்பீட்டுடன் வரும்; முன்னேற்றம் WhatsApp-ல் தெரியும்.'},
        {'q_en': 'Can I talk to you in Tamil?', 'q_ta': 'தமிழில் பேசலாமா?',
         'a_en': 'Of course. Our team speaks Tamil and English, and our WhatsApp assistant understands Tamil, Tanglish and voice notes.',
         'a_ta': 'நிச்சயமாக. எங்கள் குழு தமிழ் மற்றும் ஆங்கிலம் பேசும்; எங்கள் WhatsApp உதவியாளர் தமிழ், Tanglish, வாய்ஸ் நோட் '
                 'அனைத்தையும் புரிந்துகொள்ளும்.'},
        {'q_en': 'What happens after the project goes live?', 'q_ta': 'திட்டம் நேரலைக்கு வந்த பிறகு என்ன?',
         'a_en': 'You get free support for 30 days, then optional maintenance (AMC). We remind you before your domain, hosting '
                 'or SSL renews, so your business never goes offline.',
         'a_ta': '30 நாட்கள் இலவச ஆதரவு, அதன் பிறகு விருப்பமான பராமரிப்பு (AMC). டொமைன், ஹோஸ்டிங், SSL புதுப்பிக்க வேண்டிய '
                 'முன்பே நினைவூட்டுவோம்; உங்கள் வணிகம் ஒருபோதும் ஆஃப்லைன் ஆகாது.'},
    ]


def seo_page(request, page):
    if page not in seo_data.PAGES:
        raise Http404
    s, c = seo_data.PAGES[page]
    url = f'/{page}/'
    region_name = dict((k, (en, ta)) for k, en, ta in seo_data.REGIONS)[c['region']]
    nearby = [x for x in seo_data.CITIES if x['region'] == c['region'] and x['slug'] != c['slug']][:10]
    faqs = _faqs(s, c)
    title = f"{s['en']} in {c['en']}" + (f" ({c['alt']})" if c['alt'] else '') + ' | AJ Technologies'
    desc = (f"{s['en']} in {c['en']} by AJ Technologies: {s['intro_en']}. Tamil & English support, free quote in 24 hours "
            f"on WhatsApp.")[:300]
    json_ld = [
        {'@context': 'https://schema.org', '@type': 'Service', 'name': f"{s['en']} in {c['en']}", 'serviceType': s['en'],
         'provider': ORG, 'url': SITE + url, 'description': desc,
         'areaServed': {'@type': 'Country' if c['region'] == 'india' else 'State' if c['region'] == 'state' else 'City',
                        'name': c['en']}},
        {'@context': 'https://schema.org', '@type': 'FAQPage', 'mainEntity': [
            {'@type': 'Question', 'name': f['q_en'], 'acceptedAnswer': {'@type': 'Answer', 'text': f['a_en']}} for f in faqs]},
        _crumbs(('Home', '/'), ('Areas we serve', '/areas-we-serve/'), (f"{s['en']} in {c['en']}", url)),
    ]
    return render(request, 'seo_page.html', {
        'seo_title': title, 'seo_description': desc, 'canonical': SITE + url, 'json_ld': json_ld,
        's': s, 'c': c, 'faqs': faqs, 'region_name': region_name, 'nearby': nearby, 'services': seo_data.SERVICES,
        'other_services': [x for x in seo_data.SERVICES if x['slug'] != s['slug']], 'local': c['region'] == 'home',
        'active_nav': 'services',
        'wa_msg_en': f"Hi AJ Technologies, I'm in {c['en']} and I'd like {s['wa_en']} for my business.",
        'wa_msg_ta': f"Hi AJ Technologies, என் ஊர்: {c['ta']}. என் வணிகத்திற்கு {s['wa_ta']} வேண்டும்.",
    })


def areas(request):
    groups = []
    for key, en, ta in seo_data.REGIONS:
        cities = [c for c in seo_data.CITIES if c['region'] == key]
        groups.append({'key': key, 'en': en, 'ta': ta, 'cities': cities})
    return render(request, 'areas.html', {
        'seo_title': 'Areas We Serve: Website, App & Marketing Services in Tamil Nadu | AJ Technologies',
        'seo_description': 'AJ Technologies builds websites, online stores, mobile apps and digital marketing for businesses in '
                           'Thoothukudi, Tirunelveli, Madurai, Chennai, Coimbatore and across Tamil Nadu and India.',
        'canonical': SITE + '/areas-we-serve/', 'groups': groups, 'services': seo_data.SERVICES,
        'json_ld': [_crumbs(('Home', '/'), ('Areas we serve', '/areas-we-serve/'))],
    })


# ===========================================================================
# S. Blog
# ===========================================================================
def _posts(limit=None):
    try:
        qs = BlogPost.objects.filter(is_published=True)
        return list(qs[:limit] if limit else qs)
    except Exception:
        log.exception('Could not load blog posts')
        return []


def blog(request):
    posts = _posts()
    tag = request.GET.get('tag', '').strip()
    if tag:
        posts = [p for p in posts if tag in (p.tags or [])]
    tags = sorted({t for p in _posts() for t in (p.tags or [])})
    return render(request, 'blog.html', {
        'seo_title': 'Blog: Websites, Online Stores & Digital Marketing Tips | AJ Technologies',
        'seo_description': 'Simple, practical tips in English and Tamil to grow your business online: websites, online stores, '
                           'Google Maps, SEO and WhatsApp marketing.',
        'canonical': SITE + '/blog/', 'posts': posts, 'tags': tags, 'tag': tag, 'noindex': bool(tag),
        'json_ld': [_crumbs(('Home', '/'), ('Blog', '/blog/'))],
    })


def blog_post(request, slug):
    try:
        post = BlogPost.objects.filter(is_published=True, slug=slug).first()
    except Exception:
        log.exception('Could not load the blog post')
        post = None
    if not post:
        raise Http404
    more = [p for p in _posts(6) if p.pk != post.pk][:3]
    url = f'/blog/{post.slug}/'
    desc = post.excerpt_en or markdown_lite.plain(post.body_en, 160)
    when = post.published_at or post.created_at
    json_ld = [
        {'@context': 'https://schema.org', '@type': 'BlogPosting', 'headline': post.title_en[:110], 'description': desc,
         'datePublished': when.isoformat(), 'dateModified': post.updated_at.isoformat(), 'inLanguage': ['en', 'ta'],
         'mainEntityOfPage': SITE + url, 'author': ORG, 'publisher': ORG,
         **({'image': post.cover_url} if post.cover_url else {})},
        _crumbs(('Home', '/'), ('Blog', '/blog/'), (post.title_en, url)),
    ]
    return render(request, 'blog_post.html', {
        'seo_title': f'{post.title_en} | AJ Technologies', 'seo_description': desc, 'canonical': SITE + url,
        'og_type': 'article', 'og_image': post.cover_url, 'json_ld': json_ld, 'post': post, 'more': more,
        'body_en': markdown_lite.render(post.body_en), 'body_ta': markdown_lite.render(post.body_ta) if post.body_ta.strip() else '',
        'wa_msg_en': f'Hi AJ Technologies, I read your post "{post.title_en[:80]}" and I have a question.',
        'wa_msg_ta': f'Hi AJ Technologies, உங்கள் "{(post.title_ta or post.title_en)[:80]}" பதிவைப் படித்தேன். ஒரு கேள்வி உள்ளது.',
    })


# ===========================================================================
# T. Case studies
# ===========================================================================
CASE_COLS = ('slug', 'challenge_en', 'challenge_ta', 'solution_en', 'solution_ta', 'results_en', 'results_ta',
             'tech_used', 'duration_text')


def case_links():
    """{project id: '/portfolio/<slug>/'} for projects with a case study (empty before the v4 SQL is run)."""
    try:
        with connection.cursor() as cur:
            cur.execute("""SELECT id, slug FROM showcase_projects
                           WHERE case_study AND is_published AND NOT is_sample AND slug <> ''""")
            return {pk: f'/portfolio/{slug}/' for pk, slug in cur.fetchall()}
    except Exception:
        return {}


def case_study(request, slug):
    try:
        with connection.cursor() as cur:
            cur.execute(f"""SELECT id, {', '.join(CASE_COLS)} FROM showcase_projects
                            WHERE slug = %s AND case_study AND is_published AND NOT is_sample""", [slug])
            row = cur.fetchone()
    except Exception:
        row = None
    if not row:
        raise Http404
    case = dict(zip(CASE_COLS, row[1:]))
    if isinstance(case['tech_used'], str):
        case['tech_used'] = json.loads(case['tech_used'] or '[]')
    p = ShowcaseProject.objects.get(pk=row[0])
    try:
        review = ClientReview.objects.filter(is_published=True, project_id=p.pk).first()
    except Exception:
        review = None
    blocks = [(k, case[f'{k}_en'], case[f'{k}_ta'] or case[f'{k}_en']) for k in ('challenge', 'solution', 'results')
              if case[f'{k}_en'] or case[f'{k}_ta']]
    url = f'/portfolio/{slug}/'
    desc = (case['challenge_en'] or p.built_en or p.business_type_en)[:155]
    others = [x for x in ShowcaseProject.objects.filter(is_published=True, is_sample=False).exclude(pk=p.pk)[:3]]
    links = case_links()
    json_ld = [
        {'@context': 'https://schema.org', '@type': 'CreativeWork', 'name': f'{p.title_en}: case study', 'about': p.business_type_en,
         'description': desc, 'url': SITE + url, 'creator': ORG, **({'image': p.image_url} if p.image_url else {})},
        _crumbs(('Home', '/'), ('Portfolio', '/portfolio/'), (p.title_en, url)),
    ]
    return render(request, 'case_study.html', {
        'seo_title': f'{p.title_en}: Case Study | AJ Technologies', 'seo_description': desc, 'canonical': SITE + url,
        'og_image': p.image_url, 'json_ld': json_ld, 'p': p, 'case': case, 'blocks': blocks, 'review': review,
        'others': [(o, links.get(o.pk)) for o in others], 'active_nav': 'portfolio',
        'wa_msg_en': f"Hi AJ Technologies, I saw your {p.title_en} project. I'd like something similar for my business.",
        'wa_msg_ta': f"Hi AJ Technologies, உங்கள் {p.title_ta or p.title_en} வேலையைப் பார்த்தேன். என் வணிகத்திற்கும் இதுபோல வேண்டும்.",
    })


# ===========================================================================
# Sitemap (always https://ajtechnologiesltd.com, whatever address Render uses)
# ===========================================================================
STATIC_PAGES = [('/', 'weekly', '1.0'), ('/services/', 'monthly', '0.9'), ('/portfolio/', 'weekly', '0.8'),
                ('/contact/', 'yearly', '0.8'), ('/about/', 'yearly', '0.7'), ('/blog/', 'weekly', '0.7'),
                ('/areas-we-serve/', 'monthly', '0.7'), ('/privacy-policy/', 'yearly', '0.3'),
                ('/terms-and-conditions/', 'yearly', '0.3'), ('/service-delivery-policy/', 'yearly', '0.3')]
CONTENT_DATE = date(2026, 11, 5)          # change when you edit the static pages


def sitemap(request):
    rows = [(SITE + path, CONTENT_DATE, freq, prio) for path, freq, prio in STATIC_PAGES]
    for slug, s, c in seo_data.all_pages():
        prio = '0.7' if c['region'] == 'home' else '0.6' if c['region'] == 'tn' else '0.5'
        rows.append((f'{SITE}/{slug}/', CONTENT_DATE, 'monthly', prio))
    for p in _posts():
        rows.append((f'{SITE}/blog/{p.slug}/', timezone.localtime(p.updated_at).date(), 'monthly', '0.6'))
    try:
        with connection.cursor() as cur:
            cur.execute("""SELECT slug, updated_at FROM showcase_projects
                           WHERE case_study AND is_published AND NOT is_sample AND slug <> ''""")
            for slug, updated in cur.fetchall():
                rows.append((f'{SITE}/portfolio/{slug}/', timezone.localtime(updated).date(), 'monthly', '0.6'))
    except Exception:
        pass
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, mod, freq, prio in rows:
        xml.append(f'  <url><loc>{loc}</loc><lastmod>{mod.isoformat()}</lastmod>'
                   f'<changefreq>{freq}</changefreq><priority>{prio}</priority></url>')
    xml.append('</urlset>')
    return HttpResponse('\n'.join(xml) + '\n', content_type='application/xml; charset=utf-8')