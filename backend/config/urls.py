"""
URL configuration for the AJ Technologies admin dashboard.
"""
from django.urls import path

from main import views

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
]