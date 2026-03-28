import re

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from apps.core.uploads import sanitized_upload_path


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.slug = slugify(self.slug or self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=40, unique=True)
    slug = models.SlugField(unique=True)

    def __str__(self) -> str:
        return self.name


class ChatRoom(models.Model):
    category = models.OneToOneField(Category, on_delete=models.CASCADE, related_name="chat_room")
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.slug = slugify(self.slug or self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("forum:chatroom", kwargs={"category_slug": self.category.slug})

    @classmethod
    def for_category(cls, category: Category):
        room, _ = cls.objects.get_or_create(
            category=category,
            defaults={
                "name": category.name,
                "slug": category.slug,
                "description": category.description or f"Live chat for #{category.name}.",
            },
        )
        updates = []
        if room.name != category.name:
            room.name = category.name
            updates.append("name")
        if room.slug != category.slug:
            room.slug = category.slug
            updates.append("slug")
        expected_description = category.description or f"Live chat for #{category.name}."
        if room.description != expected_description:
            room.description = expected_description
            updates.append("description")
        if updates:
            room.save(update_fields=updates)
        return room


class Thread(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="threads")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="threads")
    title = models.CharField(max_length=180)
    body_markdown = models.TextField()
    is_locked = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    is_announcement = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deleted_threads",
    )
    deletion_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="threads")

    class Meta:
        ordering = ["-is_announcement", "-is_pinned", "-updated_at"]
        indexes = [
            models.Index(fields=["updated_at"], name="forum_thread_updated_idx"),
            models.Index(fields=["created_at"], name="forum_thread_created_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    def url_slug(self) -> str:
        return slugify(self.title) or f"thread-{self.id}"

    def get_absolute_url(self) -> str:
        return reverse(
            "forum:thread_detail",
            kwargs={
                "category_slug": slugify(self.category.slug or self.category.name),
                "thread_slug": self.url_slug(),
                "thread_id": self.id,
            },
        )


class Post(models.Model):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    body_markdown = models.TextField()
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deleted_posts",
    )
    deletion_reason = models.CharField(max_length=200, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["thread", "created_at"], name="forum_post_thread_created_idx"),
            models.Index(fields=["author", "created_at"], name="forum_post_author_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.author} reply in {self.thread}"


class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="responses",
    )
    body_markdown = models.TextField(blank=True)
    gif_url = models.URLField(blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deleted_chat_messages",
    )
    deletion_reason = models.CharField(max_length=200, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["room", "created_at"], name="forum_chat_room_created_idx"),
            models.Index(fields=["author", "created_at"], name="forum_chat_author_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.author} in {self.room}"

    def get_absolute_url(self) -> str:
        return f"{self.room.get_absolute_url()}#chat-message-{self.id}"


class ChatAttachment(models.Model):
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=sanitized_upload_path("chat-attachments"))
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    size_bytes = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        indexes = [
            models.Index(fields=["message", "uploaded_at"], name="forum_chat_attach_message_idx"),
        ]

    def __str__(self) -> str:
        return self.original_name


class Mention(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="mentions")
    mentioned_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "mentioned_user")

    def __str__(self) -> str:
        return f"@{self.mentioned_user.username} in post {self.post_id}"


class Vote(models.Model):
    TARGETS = (("thread", "Thread"), ("post", "Post"))
    target_type = models.CharField(max_length=10, choices=TARGETS)
    target_id = models.PositiveBigIntegerField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.SmallIntegerField(choices=((1, "Upvote"), (-1, "Downvote")))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("target_type", "target_id", "user")

    def __str__(self) -> str:
        return f"{self.user} {self.value} {self.target_type}:{self.target_id}"


class Attachment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=sanitized_upload_path("attachments"))
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    size_bytes = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.original_name


class Report(models.Model):
    TARGETS = (("thread", "Thread"), ("post", "Post"), ("chat_message", "Chat Message"))
    STATUSES = (
        ("open", "Open"),
        ("reviewing", "Reviewing"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    )
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_filed")
    target_type = models.CharField(max_length=16, choices=TARGETS)
    target_id = models.PositiveBigIntegerField()
    reason = models.CharField(max_length=200)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default="open")
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports_handled",
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]

    def __str__(self) -> str:
        return f"{self.target_type}:{self.target_id} ({self.status})"


class ModerationLog(models.Model):
    ACTIONS = (
        ("soft_delete", "Soft Delete"),
        ("hard_delete", "Hard Delete"),
        ("restore", "Restore"),
        ("warn_user", "Warn User"),
        ("report_resolve", "Report Resolve"),
        ("report_dismiss", "Report Dismiss"),
        ("thread_flag", "Thread Flag"),
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="moderation_actions")
    action = models.CharField(max_length=20, choices=ACTIONS)
    target_type = models.CharField(max_length=16)
    target_id = models.PositiveBigIntegerField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.actor} {self.action} {self.target_type}:{self.target_id}"


class Notification(models.Model):
    KINDS = (
        ("mention", "Mention"),
        ("reply", "Reply"),
        ("system", "System"),
    )
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications_sent",
    )
    kind = models.CharField(max_length=20, choices=KINDS)
    thread = models.ForeignKey(Thread, null=True, blank=True, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE)
    chat_room = models.ForeignKey(ChatRoom, null=True, blank=True, on_delete=models.CASCADE)
    chat_message = models.ForeignKey(ChatMessage, null=True, blank=True, on_delete=models.CASCADE)
    body = models.CharField(max_length=240, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "created_at"], name="forum_notif_recipient_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.recipient} {self.kind}"


class ReputationGrant(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reputation_grants_given",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reputation_grants_received",
    )
    thread = models.ForeignKey(Thread, null=True, blank=True, on_delete=models.CASCADE, related_name="reputation_grants")
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE, related_name="reputation_grants")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "thread"], name="forum_repgrant_actor_thread_unique"),
            models.UniqueConstraint(fields=["actor", "post"], name="forum_repgrant_actor_post_unique"),
        ]
        indexes = [
            models.Index(fields=["recipient", "created_at"], name="forum_repgrant_recipient_idx"),
        ]

    def __str__(self) -> str:
        target = f"post:{self.post_id}" if self.post_id else f"thread:{self.thread_id}"
        return f"{self.actor} +rep {self.recipient} ({target})"


class ModerationWarning(models.Model):
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="warnings_issued",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="warnings_received",
    )
    thread = models.ForeignKey(Thread, null=True, blank=True, on_delete=models.CASCADE, related_name="warnings")
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE, related_name="warnings")
    chat_message = models.ForeignKey(
        ChatMessage,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="warnings",
    )
    reason = models.CharField(max_length=200, blank=True)
    rep_penalty = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"], name="forum_warn_user_created_idx"),
        ]

    def __str__(self) -> str:
        if self.post_id:
            target = f"post:{self.post_id}"
        elif self.thread_id:
            target = f"thread:{self.thread_id}"
        else:
            target = f"chat_message:{self.chat_message_id}"
        return f"{self.moderator} warned {self.user} ({target})"


MENTION_PATTERN = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{2,30})(?![A-Za-z0-9_])")


def extract_mentions(text: str) -> list[str]:
    return sorted(set(MENTION_PATTERN.findall(text or "")))
