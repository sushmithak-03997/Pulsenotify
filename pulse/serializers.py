from django.contrib.auth.models import User
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import PriceAlert


class RegisterSerializer(serializers.Serializer):
    """Role is deliberately NOT a field: any 'role' in the body is ignored."""

    username = serializers.CharField(
        max_length=150,
        validators=[UniqueValidator(queryset=User.objects.all(), message="Username already exists.")],
    )
    password = serializers.CharField(write_only=True, min_length=6)
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class PriceAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceAlert
        fields = ["id", "origin", "destination", "threshold_price", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]  # user comes from request.user, never the body

    def validate_origin(self, value):
        return value.strip().upper()

    def validate_destination(self, value):
        return value.strip().upper()

    def validate_threshold_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Threshold price must be greater than zero.")
        return value

    def validate(self, attrs):
        if attrs["origin"] == attrs["destination"]:
            raise serializers.ValidationError("Origin and destination must be different.")
        return attrs
