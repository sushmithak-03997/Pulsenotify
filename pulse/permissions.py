from django.core.exceptions import ObjectDoesNotExist
from rest_framework.permissions import BasePermission

from .models import UserProfile


class IsAdminUser(BasePermission):
    """Allow access only to authenticated users whose profile role is ADMIN."""

    message = "Admin access required."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        try:
            return user.profile.role == UserProfile.Role.ADMIN
        except ObjectDoesNotExist:
            return False
