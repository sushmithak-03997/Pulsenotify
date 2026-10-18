import random

from django.contrib.auth import authenticate
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .constants import MOCK_PRICES
from .models import NotificationLog, PriceAlert
from .permissions import IsAdminUser
from .serializers import PriceAlertSerializer, RegisterSerializer


def _role_of(user):
    return user.profile.role


def _access_token_for(user):
    return str(RefreshToken.for_user(user).access_token)


# ------------------------------------------------------------------ auth
class RegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)  # 400 on duplicate username
        user = serializer.save()
        return Response(
            {"username": user.username, "access": _access_token_for(user), "role": _role_of(user)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password) if username and password else None
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(
            {"username": user.username, "access": _access_token_for(user), "role": _role_of(user)},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------- alerts
class AlertListCreateView(generics.ListCreateAPIView):
    """GET  /api/alerts/  -> only the caller's alerts (empty list, never 404)
    POST /api/alerts/  -> create an alert owned by request.user"""

    serializer_class = PriceAlertSerializer
    pagination_class = None  # plain JSON list

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AlertDetailView(APIView):
    """DELETE /api/alerts/<id>/ -> soft delete (status=inactive)."""

    def delete(self, request, id):
        alert = get_object_or_404(PriceAlert, id=id)
        if alert.user != request.user:
            # 404, not 403: never reveal that someone else's alert exists.
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        alert.status = PriceAlert.Status.INACTIVE
        alert.save(update_fields=["status"])
        return Response({"status": "inactive"}, status=status.HTTP_200_OK)


# ------------------------------------------------------ mock price feed
def get_flight_price(request):
    """Internal mock feed called by the check_prices Celery task. No auth."""
    route = request.GET.get("route", "")
    price_range = MOCK_PRICES.get(route)
    if not price_range:
        return JsonResponse({"error": "Route not found"}, status=404)
    price = random.randint(*price_range)
    return JsonResponse({"route": route, "price": price})


# ---------------------------------------------------------- admin summary
class AdminSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        alert_counts = PriceAlert.objects.aggregate(
            total_alerts=Count("id"),
            active_alerts=Count("id", filter=Q(status=PriceAlert.Status.ACTIVE)),
            triggered_alerts=Count("id", filter=Q(status=PriceAlert.Status.TRIGGERED)),
        )
        total_notifications = NotificationLog.objects.aggregate(total=Count("id"))["total"]

        top = (
            PriceAlert.objects.values("origin", "destination")
            .annotate(alert_count=Count("id"))
            .order_by("-alert_count", "origin", "destination")[:5]
        )
        top_routes = [
            {"route": f"{row['origin']}-{row['destination']}", "alert_count": row["alert_count"]}
            for row in top
        ]

        return Response({**alert_counts, "total_notifications": total_notifications, "top_routes": top_routes})
