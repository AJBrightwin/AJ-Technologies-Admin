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
]