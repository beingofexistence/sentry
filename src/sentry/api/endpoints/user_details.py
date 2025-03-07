import logging
from datetime import datetime

import pytz
from django.conf import settings
from django.contrib.auth import logout
from django.db import router, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import roles
from sentry.api import client
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import control_silo_endpoint
from sentry.api.bases.user import UserEndpoint
from sentry.api.decorators import sudo_required
from sentry.api.serializers import serialize
from sentry.api.serializers.models.user import DetailedSelfUserSerializer
from sentry.api.serializers.rest_framework import CamelSnakeModelSerializer, ListField
from sentry.auth.superuser import is_active_superuser
from sentry.constants import LANGUAGES
from sentry.models import Organization, OrganizationMember, OrganizationStatus, User, UserOption

audit_logger = logging.getLogger("sentry.audit.user")
delete_logger = logging.getLogger("sentry.deletions.api")


def _get_timezone_choices():
    results = []
    for tz in pytz.all_timezones:
        now = datetime.now(pytz.timezone(tz))
        offset = now.strftime("%z")
        results.append((int(offset), tz, f"(UTC{offset}) {tz}"))
    results.sort()

    for i in range(len(results)):
        results[i] = results[i][1:]
    return results


TIMEZONE_CHOICES = _get_timezone_choices()


class UserOptionsSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=LANGUAGES, required=False)
    stacktraceOrder = serializers.ChoiceField(
        choices=(
            ("-1", _("Default (let Sentry decide)")),
            ("1", _("Most recent call last")),
            ("2", _("Most recent call first")),
        ),
        required=False,
    )
    timezone = serializers.ChoiceField(choices=TIMEZONE_CHOICES, required=False)
    clock24Hours = serializers.BooleanField(required=False)
    theme = serializers.ChoiceField(
        choices=(
            ("light", _("Light")),
            ("dark", _("Dark")),
            ("system", _("Default to system")),
        ),
        required=False,
    )
    defaultIssueEvent = serializers.ChoiceField(
        choices=(
            ("recommended", _("Recommended")),
            ("latest", _("Latest")),
            ("oldest", _("Oldest")),
        ),
        required=False,
    )


class BaseUserSerializer(CamelSnakeModelSerializer):
    def validate_username(self, value):
        if (
            User.objects.filter(username__iexact=value)
            # Django throws an exception if `id` is `None`, which it will be when we're importing
            # new users via the relocation logic on the `User` model. So we cast `None` to `0` to
            # make Django happy here.
            .exclude(id=self.instance.id if hasattr(self.instance, "id") else 0).exists()
        ):
            raise serializers.ValidationError("That username is already in use.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)

        if self.instance.email == self.instance.username:
            if attrs.get("username", self.instance.email) != self.instance.email:
                # ... this probably needs to handle newsletters and such?
                attrs.setdefault("email", attrs["username"])

        return attrs

    def update(self, instance, validated_data):
        if "isActive" not in validated_data:
            validated_data["isActive"] = instance.is_active
        return super().update(instance, validated_data)


class UserSerializer(BaseUserSerializer):
    class Meta:
        model = User
        fields = ("name", "username")

    def validate(self, attrs):
        for field in settings.SENTRY_MANAGED_USER_FIELDS:
            attrs.pop(field, None)

        return super().validate(attrs)


class SuperuserUserSerializer(BaseUserSerializer):
    is_active = serializers.BooleanField()

    class Meta:
        model = User
        fields = ("name", "username", "is_active")


class PrivilegedUserSerializer(SuperuserUserSerializer):
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()

    class Meta:
        model = User
        fields = ("name", "username", "is_active", "is_staff", "is_superuser")


class DeleteUserSerializer(serializers.Serializer):
    organizations = ListField(child=serializers.CharField(required=False), required=True)
    hardDelete = serializers.BooleanField(required=False)


@control_silo_endpoint
class UserDetailsEndpoint(UserEndpoint):
    publish_status = {
        "DELETE": ApiPublishStatus.UNKNOWN,
        "GET": ApiPublishStatus.UNKNOWN,
        "PUT": ApiPublishStatus.UNKNOWN,
    }

    def get(self, request: Request, user) -> Response:
        """
        Retrieve User Details
        `````````````````````

        Return details for an account's details and options such as: full name, timezone, 24hr times, language,
        stacktrace_order.

        :auth: required
        """
        return Response(serialize(user, request.user, DetailedSelfUserSerializer()))

    def put(self, request: Request, user) -> Response:
        """
        Update Account Appearance options
        `````````````````````````````````

        Update account appearance options. Only supplied values are updated.

        :pparam string user_id: user id
        :param string language: language preference
        :param string stacktrace_order: One of -1 (default), 1 (most recent call last), 2 (most recent call first).
        :param string timezone: timezone option
        :param clock_24_hours boolean: use 24 hour clock
        :param string theme: UI theme, either "light", "dark", or "system"
        :param string default_issue_event: Event displayed by default, "recommended", "latest" or "oldest"
        :auth: required
        """
        if not request.access.has_permission("users.admin"):
            if not user.is_superuser and request.data.get("isSuperuser"):
                return Response(
                    {"detail": "Missing required permission to add superuser."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            elif not user.is_staff and request.data.get("isStaff"):
                return Response(
                    {"detail": "Missing required permission to add admin."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        if request.access.has_permission("users.admin"):
            serializer_cls = PrivilegedUserSerializer
        elif is_active_superuser(request):
            serializer_cls = SuperuserUserSerializer
        else:
            serializer_cls = UserSerializer
        serializer = serializer_cls(instance=user, data=request.data, partial=True)

        serializer_options = UserOptionsSerializer(
            data=request.data.get("options", {}), partial=True
        )

        # This serializer should NOT include privileged fields e.g. password
        if not serializer.is_valid() or not serializer_options.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # map API keys to keys in model
        key_map = {
            "theme": "theme",
            "language": "language",
            "timezone": "timezone",
            "stacktraceOrder": "stacktrace_order",
            "defaultIssueEvent": "default_issue_event",
            "clock24Hours": "clock_24_hours",
        }

        options_result = serializer_options.validated_data

        for key in key_map:
            if key in options_result:
                UserOption.objects.set_value(
                    user=user, key=key_map.get(key, key), value=options_result.get(key)
                )

        with transaction.atomic(using=router.db_for_write(User)):
            user = serializer.save()

            if any(k in request.data for k in ("isStaff", "isSuperuser", "isActive")):
                audit_logger.info(
                    "user.edit",
                    extra={
                        "user_id": user.id,
                        "actor_id": request.user.id,
                        "form_data": request.data,
                    },
                )

        return Response(serialize(user, request.user, DetailedSelfUserSerializer()))

    @sudo_required
    def delete(self, request: Request, user) -> Response:
        """
        Delete User Account

        Also removes organizations if they are an owner
        :pparam string user_id: user id
        :param boolean hard_delete: Completely remove the user from the database (requires super user)
        :param list organizations: List of organization ids to remove
        :auth required:
        """

        serializer = DeleteUserSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # from `frontend/remove_account.py`
        org_list = Organization.objects.filter(
            member_set__role__in=[x.id for x in roles.with_scope("org:admin")],
            member_set__user_id=user.id,
            status=OrganizationStatus.ACTIVE,
        )

        org_results = []
        for org in org_list:
            org_results.append({"organization": org, "single_owner": org.has_single_owner()})

        avail_org_slugs = {o["organization"].slug for o in org_results}
        orgs_to_remove = set(serializer.validated_data.get("organizations")).intersection(
            avail_org_slugs
        )

        for result in org_results:
            if result["single_owner"]:
                orgs_to_remove.add(result["organization"].slug)

        for org_slug in orgs_to_remove:
            client.delete(path=f"/organizations/{org_slug}/", request=request, is_sudo=True)

        remaining_org_ids = [
            o.id for o in org_list if o.slug in avail_org_slugs.difference(orgs_to_remove)
        ]

        if remaining_org_ids:
            for member in OrganizationMember.objects.filter(
                organization__in=remaining_org_ids, user_id=user.id
            ):
                member.delete()

        logging_data = {
            "actor_id": request.user.id,
            "ip_address": request.META["REMOTE_ADDR"],
            "user_id": user.id,
        }

        hard_delete = serializer.validated_data.get("hardDelete", False)

        # Only active superusers can hard delete accounts
        if hard_delete and not request.access.has_permission("users.admin"):
            return Response(
                {"detail": "Missing required permission to hard delete account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        is_current_user = request.user.id == user.id

        if hard_delete:
            user.delete()
            delete_logger.info("user.removed", extra=logging_data)
        else:
            User.objects.filter(id=user.id).update(is_active=False)
            delete_logger.info("user.deactivate", extra=logging_data)

        # if the user deleted their own account log them out
        if is_current_user:
            logout(request)

        return Response(status=status.HTTP_204_NO_CONTENT)
