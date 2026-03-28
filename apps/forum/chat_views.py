from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.core.context_processors import invalidate_notification_count
from apps.core.models import SiteBranding
from apps.core.ratelimit import rate_limit
from apps.core.uploads import sanitize_original_name
from apps.forum.forms import ChatMessageForm
from apps.forum.models import Category, ChatAttachment, ChatMessage, ChatRoom, Notification, Thread, extract_mentions
from apps.forum.stats import apply_user_forum_stats, build_user_forum_stats
from apps.forum.views import apply_thread_mention_state, categories_with_hot_threads, mentionable_users_payload, role_rank

User = get_user_model()

CHATROOM_MESSAGE_LIMIT = 120
CHATROOM_PARTICIPANT_LIMIT = 15


def active_klipy_settings() -> tuple[str, str]:
    branding = SiteBranding.objects.only("klipy_app_key", "klipy_content_filter").order_by("id").first()
    app_key = (getattr(branding, "klipy_app_key", "") or settings.KLIPY_APP_KEY).strip()
    content_filter = (getattr(branding, "klipy_content_filter", "") or settings.KLIPY_CONTENT_FILTER).strip() or "medium"
    return app_key, content_filter


def parse_positive_int(value, default: int = 0) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def default_chat_category():
    return Category.objects.filter(is_public=True).order_by("name").first()


def chat_category_or_404(category_slug: str) -> Category:
    return get_object_or_404(Category, slug=category_slug, is_public=True)


def chatroom_for_category(category: Category) -> ChatRoom:
    return ChatRoom.for_category(category)


def mark_chatroom_notifications_read(user, room: ChatRoom) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    updated = Notification.objects.filter(recipient=user, chat_room=room, is_read=False).update(is_read=True)
    if updated:
        invalidate_notification_count(user.id)


def chatroom_queryset(room: ChatRoom, user, *, limit: int | None = None):
    queryset = (
        room.messages.select_related("author", "reply_to", "reply_to__author", "room", "room__category")
        .prefetch_related("attachments", "author__groups", "reply_to__author__groups")
        .order_by("-created_at")
    )
    if not getattr(user, "has_perm", lambda *_args, **_kwargs: False)("forum.change_post"):
        queryset = queryset.filter(is_deleted=False)
    if limit:
        queryset = queryset[:limit]
    return queryset


def chat_message_excerpt(message: ChatMessage) -> str:
    if message.body_markdown.strip():
        return message.body_markdown.strip().replace("\n", " ")[:120]
    if message.gif_url:
        return "GIF reply"
    if getattr(message, "attachments_cache", None):
        return "Image reply"
    if getattr(message, "attachments_count", None):
        return "Image reply"
    return "Reply"


def annotate_chat_messages(messages_list: list[ChatMessage], viewer, previous_message: ChatMessage | None = None) -> list[ChatMessage]:
    author_ids = {message.author_id for message in messages_list if message.author_id}
    reply_author_ids = {
        message.reply_to.author_id
        for message in messages_list
        if message.reply_to_id and message.reply_to and message.reply_to.author_id
    }
    stats = build_user_forum_stats(list(author_ids | reply_author_ids))
    prior = previous_message
    for message in messages_list:
        message.attachments_cache = list(message.attachments.all())
        apply_user_forum_stats(message.author, stats)
        if message.reply_to_id and message.reply_to:
            apply_user_forum_stats(message.reply_to.author, stats)
            message.reply_preview = chat_message_excerpt(message.reply_to)
        else:
            message.reply_preview = ""
        message.is_klipy_gif = "klipy.com" in (message.gif_url or "")
        time_gap = None
        if prior and prior.created_at and message.created_at:
            time_gap = message.created_at - prior.created_at
        message.show_identity = (
            prior is None
            or prior.author_id != message.author_id
            or time_gap is None
            or time_gap >= timedelta(hours=12)
        )
        message.is_continuation = not message.show_identity
        message.can_warn_author = viewer.has_perm("forum.change_post") and viewer.id != message.author_id
        message.can_soft_delete = viewer.has_perm("forum.change_post")
        message.can_report = viewer.is_authenticated and viewer.has_perm("forum.add_report")
        message.has_actions = bool(
            (viewer.is_authenticated and not message.is_deleted)
            or message.can_report
            or message.can_warn_author
            or message.can_soft_delete
        )
        message.user_role_rank = role_rank(message.author)
        prior = message
    return messages_list


def recent_chat_participants(room: ChatRoom) -> tuple[list, int]:
    recent_messages = list(
        room.messages.filter(is_deleted=False)
        .select_related("author")
        .order_by("-created_at")
        .values_list("author_id", flat=True)[:200]
    )
    seen: set[int] = set()
    ordered_ids: list[int] = []
    for author_id in recent_messages:
        if author_id in seen:
            continue
        seen.add(author_id)
        ordered_ids.append(author_id)
        if len(ordered_ids) >= CHATROOM_PARTICIPANT_LIMIT:
            break
    participants_by_id = {
        user.id: user
        for user in User.objects.filter(id__in=ordered_ids).select_related("presence").prefetch_related("groups")
    }
    stats = build_user_forum_stats(ordered_ids)
    participants = []
    for user_id in ordered_ids:
        participant = participants_by_id.get(user_id)
        if not participant:
            continue
        participant.is_currently_online = hasattr(participant, "presence") and participant.presence.is_online
        apply_user_forum_stats(participant, stats)
        participants.append(participant)
    total = room.messages.filter(is_deleted=False).values("author_id").distinct().count()
    return participants, total


def category_topics_for_chat(category: Category, user, *, limit: int = 3):
    threads = (
        Thread.objects.filter(category=category, is_deleted=False)
        .select_related("author", "category")
        .prefetch_related("tags")
        .annotate(reply_count=Count("posts", filter=Q(posts__is_deleted=False)))
        .order_by("-updated_at", "-created_at")[:limit]
    )
    return apply_thread_mention_state(user, threads)


def chatroom_sidebar_context(request, room: ChatRoom) -> dict:
    participants, participant_total = recent_chat_participants(room)
    visible_messages = chatroom_queryset(room, request.user)
    latest_message_id = visible_messages.values_list("id", flat=True).first() or 0
    message_count = room.messages.filter(is_deleted=False).count()
    return {
        "chatroom": room,
        "chatroom_participants": participants,
        "chatroom_participant_total": participant_total,
        "chatroom_message_count": message_count,
        "chatroom_last_message_id": latest_message_id,
    }


def chatroom_context(request, category: Category, room: ChatRoom) -> dict:
    messages_list = list(reversed(chatroom_queryset(room, request.user, limit=CHATROOM_MESSAGE_LIMIT)))
    annotate_chat_messages(messages_list, request.user)
    pinned_topics = category_topics_for_chat(category, request.user, limit=3)
    klipy_app_key, klipy_content_filter = active_klipy_settings()
    context = {
        "room": room,
        "category": category,
        "chat_messages": messages_list,
        "chat_can_post": request.user.is_authenticated and request.user.has_perm("forum.add_post"),
        "chat_form": ChatMessageForm(),
        "categories": categories_with_hot_threads(request.user),
        "active_category_slug": category.slug,
        "mentionable_users": mentionable_users_payload(),
        "klipy_enabled": bool(klipy_app_key),
        "klipy_app_key": klipy_app_key,
        "klipy_api_base": settings.KLIPY_API_BASE,
        "klipy_content_filter": klipy_content_filter,
        "klipy_attribution_url": settings.KLIPY_ATTRIBUTION_URL,
        "chatroom_pinned_topics": pinned_topics,
        "category_topics_url": f"{reverse('forum:home')}?category={category.slug}",
        "category_topic_total": Thread.objects.filter(category=category, is_deleted=False).count(),
    }
    context.update(chatroom_sidebar_context(request, room))
    return context


def create_chat_notifications(message: ChatMessage, sender) -> None:
    mentioned_usernames = extract_mentions(message.body_markdown)
    recipients: set[int] = set()
    mentioned_users = []
    if mentioned_usernames:
        mentioned_users = list(User.objects.filter(username__in=mentioned_usernames, is_active=True).exclude(id=sender.id))
        Notification.objects.bulk_create(
            [
                Notification(
                    recipient=user,
                    actor=sender,
                    kind="mention",
                    chat_room=message.room,
                    chat_message=message,
                    body=f"{sender.username} mentioned you in #{message.room.category.name} chat",
                )
                for user in mentioned_users
            ]
        )
        recipients.update(user.id for user in mentioned_users)
    if message.reply_to_id and message.reply_to and message.reply_to.author_id not in recipients and message.reply_to.author_id != sender.id:
        Notification.objects.create(
            recipient=message.reply_to.author,
            actor=sender,
            kind="reply",
            chat_room=message.room,
            chat_message=message,
            body=f"{sender.username} replied to your chat message in #{message.room.category.name}",
        )
        recipients.add(message.reply_to.author_id)
    invalidate_notification_count(*recipients)


def serialize_form_errors(form: ChatMessageForm) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for field, field_errors in form.errors.items():
        errors[field] = [str(error) for error in field_errors]
    return errors


def render_chat_message_html(request, message: ChatMessage, previous_message: ChatMessage | None = None) -> str:
    annotate_chat_messages([message], request.user, previous_message=previous_message)
    return render_to_string("forum/partials/chat_message.html", {"message": message}, request=request)


def render_chat_participants_html(request, room: ChatRoom) -> str:
    context = chatroom_sidebar_context(request, room)
    return render_to_string("forum/partials/chat_participants.html", context, request=request)


@require_GET
def chatroom_root(request: HttpRequest) -> HttpResponse:
    category = default_chat_category()
    if not category:
        return redirect("forum:home")
    return redirect(chatroom_for_category(category).get_absolute_url())


@require_GET
def chatroom_view(request: HttpRequest, category_slug: str) -> HttpResponse:
    category = chat_category_or_404(category_slug)
    room = chatroom_for_category(category)
    if not room.is_public and not request.user.is_authenticated:
        raise Http404("Chatroom not found.")
    mark_chatroom_notifications_read(request.user, room)
    context = chatroom_context(request, category, room)
    return render(request, "forum/chatroom.html", context)


@login_required
@permission_required("forum.add_post", raise_exception=True)
@require_POST
@rate_limit(key_prefix="chat_post", max_ip_hits=80, max_user_hits=40, window_seconds=60)
def chatroom_send(request: HttpRequest, category_slug: str) -> HttpResponse:
    category = chat_category_or_404(category_slug)
    room = chatroom_for_category(category)
    form = ChatMessageForm(request.POST, request.FILES)
    if not form.is_valid():
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "errors": serialize_form_errors(form)}, status=400)
        messages.error(request, "Could not send chat message. Please review the form.")
        return redirect(room.get_absolute_url())

    message = form.save(commit=False)
    message.room = room
    message.author = request.user
    reply_to_id = parse_positive_int(request.POST.get("reply_to_id"))
    if reply_to_id:
        message.reply_to = room.messages.filter(id=reply_to_id).first()
    message.save()
    attachments = form.cleaned_data.get("attachments") or []
    for file in attachments:
        ChatAttachment.objects.create(
            message=message,
            file=file,
            original_name=sanitize_original_name(file.name),
            mime_type=file.content_type or "",
            size_bytes=file.size,
        )
    previous_message = (
        room.messages.filter(is_deleted=False, created_at__lt=message.created_at)
        .select_related("author", "reply_to", "reply_to__author", "room", "room__category")
        .prefetch_related("attachments", "author__groups", "reply_to__author__groups")
        .order_by("-created_at")
        .first()
    )
    message = (
        room.messages.select_related("author", "reply_to", "reply_to__author", "room", "room__category")
        .prefetch_related("attachments", "author__groups", "reply_to__author__groups")
        .get(id=message.id)
    )
    create_chat_notifications(message, request.user)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "message_id": message.id,
                "message_html": render_chat_message_html(request, message, previous_message=previous_message),
                "participants_html": render_chat_participants_html(request, room),
            }
        )
    messages.success(request, "Message sent.")
    return redirect(f"{room.get_absolute_url()}#chat-message-{message.id}")


@require_GET
@rate_limit(key_prefix="chat_updates", max_ip_hits=300, max_user_hits=240, window_seconds=60)
def chatroom_updates(request: HttpRequest, category_slug: str) -> JsonResponse:
    category = chat_category_or_404(category_slug)
    room = chatroom_for_category(category)
    after_id = parse_positive_int(request.GET.get("after"))
    queryset = chatroom_queryset(room, request.user).filter(id__gt=after_id).order_by("created_at")[:40]
    messages_list = list(queryset)
    if not messages_list:
        mark_chatroom_notifications_read(request.user, room)
        return JsonResponse({"ok": True, "messages": [], "latest_id": after_id})
    previous_message = None
    if after_id:
        previous_message = (
            chatroom_queryset(room, request.user)
            .filter(id__lte=after_id)
            .order_by("-created_at")
            .first()
        )
    annotate_chat_messages(messages_list, request.user, previous_message=previous_message)
    payload = [
        {
            "id": message.id,
            "html": render_to_string("forum/partials/chat_message.html", {"message": message}, request=request),
        }
        for message in messages_list
    ]
    mark_chatroom_notifications_read(request.user, room)
    return JsonResponse(
        {
            "ok": True,
            "messages": payload,
            "latest_id": messages_list[-1].id,
            "participants_html": render_chat_participants_html(request, room),
        }
    )


@require_GET
def user_chat_messages(request: HttpRequest, username: str) -> HttpResponse:
    profile_user = get_object_or_404(User, username=username, is_active=True)
    messages_list = list(
        ChatMessage.objects.filter(author=profile_user, is_deleted=False)
        .select_related("author", "reply_to", "reply_to__author", "room", "room__category")
        .prefetch_related("attachments", "author__groups", "reply_to__author__groups")
        .order_by("-created_at")[:100]
    )
    for message in messages_list:
        message.attachments_cache = list(message.attachments.all())
        message.show_identity = True
        message.is_continuation = False
        message.room_label = f"#{message.room.category.name}" if getattr(message.room, "category", None) else ""
        if message.reply_to_id and message.reply_to:
            message.reply_preview = chat_message_excerpt(message.reply_to)
        else:
            message.reply_preview = ""
        message.is_klipy_gif = "klipy.com" in (message.gif_url or "")
        message.can_warn_author = request.user.has_perm("forum.change_post") and request.user.id != message.author_id
        message.can_soft_delete = request.user.has_perm("forum.change_post")
        message.can_report = request.user.is_authenticated and request.user.has_perm("forum.add_report")
        message.has_actions = bool(
            (request.user.is_authenticated and not message.is_deleted)
            or message.can_report
            or message.can_warn_author
            or message.can_soft_delete
        )
    stats = build_user_forum_stats([profile_user.id])
    apply_user_forum_stats(profile_user, stats)
    return render(
        request,
        "forum/chat_user_posts.html",
        {
            "profile_user": profile_user,
            "chat_messages": messages_list,
            "categories": categories_with_hot_threads(request.user),
        },
    )
