from django.contrib import admin

from .models import (
    Attachment,
    Category,
    ChatAttachment,
    ChatMessage,
    ChatRoom,
    Mention,
    ModerationLog,
    ModerationWarning,
    Notification,
    Post,
    Report,
    ReputationGrant,
    Tag,
    Thread,
    Vote,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_public")
    search_fields = ("name", "slug")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_public", "updated_at")
    search_fields = ("name", "slug", "description")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "author", "reply_to", "is_deleted", "created_at", "edited_at")
    list_filter = ("room", "is_deleted")
    search_fields = ("body_markdown", "author__username", "giphy_url")


@admin.register(ChatAttachment)
class ChatAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "original_name", "mime_type", "size_bytes", "uploaded_at")


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "author", "category", "is_announcement", "is_pinned", "is_locked", "is_deleted")
    list_filter = ("is_announcement", "is_pinned", "is_locked", "is_deleted", "category")
    search_fields = ("title", "body_markdown", "author__username")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "author", "is_deleted", "created_at", "edited_at")
    list_filter = ("is_deleted",)
    search_fields = ("body_markdown", "author__username")


@admin.register(Mention)
class MentionAdmin(admin.ModelAdmin):
    list_display = ("post", "mentioned_user", "created_at")


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("target_type", "target_id", "user", "value", "created_at")
    list_filter = ("target_type", "value")


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "original_name", "mime_type", "size_bytes", "uploaded_at")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "reporter", "target_type", "target_id", "status", "created_at", "handled_by")
    list_filter = ("status", "target_type")
    search_fields = ("reason", "details", "reporter__username")


@admin.register(ModerationLog)
class ModerationLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "target_id")
    list_filter = ("action", "target_type")
    search_fields = ("notes", "actor__username")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "kind", "is_read", "created_at")
    list_filter = ("kind", "is_read")
    search_fields = ("body", "recipient__username", "actor__username")


@admin.register(ReputationGrant)
class ReputationGrantAdmin(admin.ModelAdmin):
    list_display = ("id", "actor", "recipient", "thread", "post", "created_at")
    search_fields = ("actor__username", "recipient__username")


@admin.register(ModerationWarning)
class ModerationWarningAdmin(admin.ModelAdmin):
    list_display = ("id", "moderator", "user", "rep_penalty", "thread", "post", "created_at")
    search_fields = ("moderator__username", "user__username", "reason")
