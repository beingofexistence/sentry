from __future__ import annotations

from django.db import models
from django.db.models.signals import pre_delete
from django.utils import timezone

from sentry.backup.scopes import RelocationScope
from sentry.constants import ObjectStatus
from sentry.db.mixin import PendingDeletionMixin, delete_pending_deletion_option
from sentry.db.models import (
    BoundedBigIntegerField,
    BoundedPositiveIntegerField,
    JSONField,
    Model,
    region_silo_only_model,
    sane_repr,
)
from sentry.services.hybrid_cloud.user import RpcUser
from sentry.signals import pending_delete


@region_silo_only_model
class Repository(Model, PendingDeletionMixin):
    __relocation_scope__ = RelocationScope.Global

    organization_id = BoundedBigIntegerField(db_index=True)
    name = models.CharField(max_length=200)
    url = models.URLField(null=True)
    provider = models.CharField(max_length=64, null=True)
    # The external_id is the id of the repo in the provider's system. (e.g. GitHub's repo id)
    external_id = models.CharField(max_length=64, null=True)
    config = JSONField(default=dict)
    status = BoundedPositiveIntegerField(
        default=ObjectStatus.ACTIVE, choices=ObjectStatus.as_choices(), db_index=True
    )
    date_added = models.DateTimeField(default=timezone.now)
    integration_id = BoundedPositiveIntegerField(db_index=True, null=True)

    class Meta:
        app_label = "sentry"
        db_table = "sentry_repository"
        unique_together = (("organization_id", "provider", "external_id"),)

    __repr__ = sane_repr("organization_id", "name", "provider")

    _rename_fields_on_pending_delete = frozenset(["name", "external_id"])

    def has_integration_provider(self):
        return self.provider and self.provider.startswith("integrations:")

    def get_provider(self):
        from sentry.plugins.base import bindings

        if self.has_integration_provider():
            provider_cls = bindings.get("integration-repository.provider").get(self.provider)
            return provider_cls(self.provider)

        provider_cls = bindings.get("repository.provider").get(self.provider)
        return provider_cls(self.provider)

    def generate_delete_fail_email(self, error_message):
        from sentry.utils.email import MessageBuilder

        new_context = {
            "repo": self,
            "error_message": error_message,
            "provider_name": self.get_provider().name,
        }

        return MessageBuilder(
            subject="Unable to Delete Repository Webhooks",
            context=new_context,
            template="sentry/emails/unable-to-delete-repo.txt",
            html_template="sentry/emails/unable-to-delete-repo.html",
        )

    def rename_on_pending_deletion(
        self,
        fields: set[str] | None = None,
        extra_fields_to_save: list[str] | None = None,
    ) -> None:
        # Due to the fact that Repository is shown to the user
        # as it is pending deletion, this is added to display the fields
        # correctly to the user.
        self.config["pending_deletion_name"] = self.name
        super().rename_on_pending_deletion(fields, ["config"])

    def reset_pending_deletion_field_names(
        self,
        extra_fields_to_save: list[str] | None = None,
    ) -> bool:
        del self.config["pending_deletion_name"]
        return super().reset_pending_deletion_field_names(["config"])


def on_delete(instance, actor: RpcUser | None = None, **kwargs):
    """
    Remove webhooks for repository providers that use repository level webhooks.
    This is called from sentry.tasks.deletion.run_deletion()
    """
    # If there is no provider, we don't have any webhooks, etc to delete
    if not instance.provider:
        return

    def handle_exception(e):
        from sentry.exceptions import InvalidIdentity, PluginError
        from sentry.shared_integrations.exceptions import IntegrationError

        if isinstance(e, (IntegrationError, PluginError, InvalidIdentity)):
            error = str(e)
        else:
            error = "An unknown error occurred"
        if actor is not None:
            msg = instance.generate_delete_fail_email(error)
            msg.send_async(to=[actor.email])

    if instance.has_integration_provider():
        try:
            instance.get_provider().on_delete_repository(repo=instance)
        except Exception as exc:
            handle_exception(exc)
    else:
        try:
            instance.get_provider().delete_repository(repo=instance, actor=actor)
        except Exception as exc:
            handle_exception(exc)


pending_delete.connect(on_delete, sender=Repository, weak=False)
pre_delete.connect(delete_pending_deletion_option, sender=Repository, weak=False)
