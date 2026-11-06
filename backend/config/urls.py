"""
URL configuration for the AJ Technologies admin dashboard.
"""
from django.urls import path

from main import views, views_v4

urlpatterns = [
    # The dashboard page
    path('', views.index, name='index'),

    # Login
    path('api/login/', views.login_view, name='api_login'),
    path('api/logout/', views.logout_view, name='api_logout'),
    path('api/me/', views.me, name='api_me'),
    path('api/status/', views.status, name='api_status'),

    # Enquiries (contact_enquiries table)
    path('api/enquiries/', views.enquiries, name='api_enquiries'),
    path('api/enquiries/bulk/', views.enquiries_bulk, name='api_enquiries_bulk'),
    path('api/enquiries/<int:pk>/', views.enquiry_detail, name='api_enquiry'),

    # Projects (showcase_projects table)
    path('api/projects/', views.projects, name='api_projects'),
    path('api/projects/reorder/', views.projects_reorder, name='api_projects_reorder'),
    path('api/projects/<int:pk>/', views.project_detail, name='api_project'),

    # Client reviews (client_reviews table)
    path('api/reviews/', views.reviews, name='api_reviews'),
    path('api/reviews/reorder/', views.reviews_reorder, name='api_reviews_reorder'),
    path('api/reviews/<int:pk>/', views.review_detail, name='api_review'),

    # Images (Supabase Storage bucket "project-images")
    path('api/images/', views.images, name='api_images'),

    # WhatsApp (tables from supabase_whatsapp.sql, filled by the WhatsApp bot)
    path('api/wa/chats/', views.wa_chats, name='api_wa_chats'),
    path('api/wa/chats/<str:wa_id>/', views.wa_chat, name='api_wa_chat'),
    path('api/wa/chats/<str:wa_id>/read/', views.wa_read, name='api_wa_read'),
    path('api/wa/chats/<str:wa_id>/send/', views.wa_send, name='api_wa_send'),
    path('api/wa/chats/<str:wa_id>/review/', views.wa_review_request, name='api_wa_review'),
    path('api/wa/templates/', views.wa_templates, name='api_wa_templates'),
    path('api/wa/templates/send/', views.wa_send_template, name='api_wa_template_send'),
    path('api/wa/media/<str:media_id>/', views.wa_media, name='api_wa_media'),
    path('api/wa/bookings/', views.wa_bookings, name='api_wa_bookings'),
    path('api/wa/bookings/<int:pk>/', views.wa_booking, name='api_wa_booking'),
    path('api/wa/broadcasts/', views.wa_broadcasts, name='api_wa_broadcasts'),
    path('api/wa/broadcasts/<int:pk>/cancel/', views.wa_broadcast_cancel, name='api_wa_broadcast_cancel'),

    # Upgrade v2: clients, knowledge, reports (tables from supabase_upgrade_v2.sql)
    path('api/clients/projects/', views.client_projects, name='api_client_projects'),
    path('api/clients/projects/<int:pk>/', views.client_project, name='api_client_project'),
    path('api/clients/projects/<int:pk>/notify/', views.client_project_notify, name='api_client_project_notify'),
    path('api/clients/renewals/', views.client_renewals, name='api_client_renewals'),
    path('api/clients/renewals/<int:pk>/', views.client_renewal, name='api_client_renewal'),
    path('api/clients/tickets/', views.client_tickets, name='api_client_tickets'),
    path('api/clients/tickets/<int:pk>/', views.client_ticket, name='api_client_ticket'),
    path('api/knowledge/', views.knowledge, name='api_knowledge'),
    path('api/knowledge/<int:pk>/', views.knowledge_item, name='api_knowledge_item'),
    path('api/knowledge/unanswered/<int:pk>/', views.unanswered_item, name='api_unanswered_item'),
    path('api/reports/', views.reports, name='api_reports'),

    # Upgrade v4: billing, money, subscriptions, blog (tables from supabase_upgrade_v4.sql)
    path('api/billing/docs/', views_v4.billing_docs, name='api_billing_docs'),
    path('api/billing/docs/<int:pk>/', views_v4.billing_doc, name='api_billing_doc'),
    path('api/billing/docs/<int:pk>/pdf/', views_v4.billing_pdf, name='api_billing_pdf'),
    path('api/billing/docs/<int:pk>/send/', views_v4.billing_send, name='api_billing_send'),
    path('api/billing/docs/<int:pk>/convert/', views_v4.billing_convert, name='api_billing_convert'),
    path('api/billing/docs/<int:pk>/link/', views_v4.billing_link, name='api_billing_link'),
    path('api/billing/docs/<int:pk>/payments/', views_v4.billing_add_payment, name='api_billing_add_payment'),
    path('api/billing/payments/', views_v4.billing_payments, name='api_billing_payments'),
    path('api/billing/payments/<int:pk>/', views_v4.billing_payment, name='api_billing_payment'),
    path('api/billing/settings/', views_v4.billing_settings, name='api_billing_settings'),
    path('api/money/', views_v4.money, name='api_money'),
    path('api/money/expenses/', views_v4.expenses, name='api_expenses'),
    path('api/money/expenses/<int:pk>/', views_v4.expense, name='api_expense'),
    path('api/subscriptions/', views_v4.subscriptions, name='api_subscriptions'),
    path('api/subscriptions/<int:pk>/', views_v4.subscription, name='api_subscription'),
    path('api/subscriptions/<int:pk>/renewed/', views_v4.subscription_renewed, name='api_subscription_renewed'),
    path('api/blog/', views_v4.blog, name='api_blog'),
    path('api/blog/<int:pk>/', views_v4.blog_post, name='api_blog_post'),
    path('api/v4/extras/', views_v4.extras, name='api_v4_extras'),
    path('api/projects/<int:pk>/case/', views_v4.project_case, name='api_project_case'),
    path('api/clients/projects/<int:pk>/review/', views_v4.client_project_review, name='api_client_project_review'),
]