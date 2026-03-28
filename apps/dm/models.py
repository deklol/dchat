from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.uploads import sanitized_upload_path
from apps.dm.crypto import decrypt_text, encrypt_text


class DirectConversation(models.Model):
    user_low = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dm_conversations_low")
    user_high = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dm_conversations_high")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_low", "user_high"], name="uniq_dm_user_pair"),
            models.CheckConstraint(check=~Q(user_low=models.F("user_high")), name="chk_dm_not_same_user"),
        ]
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["updated_at"]),
        ]

    @classmethod
    def for_users(cls, user_a, user_b):
        low_id, high_id = sorted([user_a.id, user_b.id])
        return cls.objects.get_or_create(user_low_id=low_id, user_high_id=high_id)[0]

    def other_for(self, user):
        return self.user_high if user.id == self.user_low_id else self.user_low

    def __str__(self) -> str:
        return f"DM {self.user_low_id}:{self.user_high_id}"


class DirectMessagePreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dm_preference")
    allow_incoming = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def for_user(cls, user):
        preference, _ = cls.objects.get_or_create(user=user)
        return preference

    def __str__(self) -> str:
        return f"DM preference {self.user_id} incoming={self.allow_incoming}"


class DirectMessage(models.Model):
    conversation = models.ForeignKey(DirectConversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dm_messages_sent")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dm_messages_received")
    body_encrypted = models.TextField()
    is_read = models.BooleanField(default=False)
    is_reported = models.BooleanField(default=False)
    report_reason = models.CharField(max_length=200, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dm_reports_filed",
    )
    reported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["recipient", "is_read", "created_at"]),
        ]

    def set_body(self, plaintext: str) -> None:
        self.body_encrypted = encrypt_text(plaintext)

    def get_body(self) -> str:
        return decrypt_text(self.body_encrypted)

    def mark_reported(self, reporter, reason: str) -> None:
        self.is_reported = True
        self.report_reason = reason[:200]
        self.reported_by = reporter
        self.reported_at = timezone.now()

    def __str__(self) -> str:
        return f"DM {self.id} in {self.conversation_id}"


class DirectMessageAttachment(models.Model):
    message = models.ForeignKey(DirectMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=sanitized_upload_path("dm-attachments"))
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    size_bytes = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        indexes = [
            models.Index(fields=["message", "uploaded_at"], name="dm_attach_message_idx"),
        ]

    def __str__(self) -> str:
        return self.original_name
