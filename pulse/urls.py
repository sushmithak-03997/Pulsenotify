from django.urls import path

from . import views

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("alerts/", views.AlertListCreateView.as_view(), name="alerts"),
    path("alerts/<int:id>/", views.AlertDetailView.as_view(), name="alert-detail"),
    path("flights/price/", views.get_flight_price, name="flight-price"),
    path("admin/summary/", views.AdminSummaryView.as_view(), name="admin-summary"),
]
