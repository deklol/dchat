from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max, Q, Count, OuterRef, Subquery
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core.ratelimit import rate_limit
from apps.dm.context_processors import invalidate_dm_context
from apps.dm.forms import (
    DirectMessageForm,
    DirectMessagePreferenceForm,
    QuickDirectMessageForm,
    ReportDirectMessageForm,
    StartDirectMessageForm,
)
from apps.dm.models import DirectConversation, DirectMessage, DirectMessageAttachment, DirectMessagePreference
User = get_user_model()


def _target_user_or_404(user, username: str) -> User:
    target = get_object_or_404(User, username=username, is_active=True)
    if target.id == user.id:
        raise Http404("Cannot DM yourself.")
    return target


def _incoming_dm_allowed(user) -> bool:
    allowed = DirectMessagePreference.objects.filter(user=user).values_list("allow_incoming", flat=True).first()
    return True if allowed is None else bool(allowed)


def _safe_next_url(request: HttpRequest, fallback: str) -> str:
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


def _send_dm(conversation: DirectConversation, sender, recipient, body: str, attachments=None) -> None:
    message = DirectMessage(
        conversation=conversation,
        sender=sender,
        recipient=recipient,
    )
    message.set_body(body)
    message.save()
    for file in attachments or []:
        DirectMessageAttachment.objects.create(
            message=message,
            file=file,
            original_name=file.name,
            mime_type=file.content_type or "",
            size_bytes=file.size,
        )
    conversation.save(update_fields=["updated_at"])
    invalidate_dm_context(sender.id, recipient.id)


def _decrypted_messages_for(user, conversation: DirectConversation) -> list[DirectMessage]:
    messages_qs = conversation.messages.select_related("sender", "recipient", "reported_by").prefetch_related("attachments")
    updated_count = messages_qs.filter(recipient=user, is_read=False).update(is_read=True)
    if updated_count:
        invalidate_dm_context(user.id)
    dm_messages = list(messages_qs)
    for message in dm_messages:
        try:
            message.body_plain = message.get_body()
        except Exception:
            message.body_plain = "[encrypted message]"
    return dm_messages


@login_required
def dm_inbox(request: HttpRequest) -> HttpResponse:
    last_message_id = Subquery(
        DirectMessage.objects.filter(conversation=OuterRef("pk"))
        .order_by("-created_at")
        .values("id")[:1]
    )
    conversations = list(
        DirectConversation.objects.filter(Q(user_low=request.user) | Q(user_high=request.user))
        .select_related("user_low", "user_high", "user_low__presence", "user_high__presence")
        .annotate(
            last_message_at=Max("messages__created_at"),
            unread_count=Count("messages", filter=Q(messages__recipient=request.user, messages__is_read=False)),
            last_message_id=last_message_id,
        )
        .order_by("-last_message_at", "-updated_at")
    )
    last_ids = [c.last_message_id for c in conversations if c.last_message_id]
    last_messages = {
        m.id: m
        for m in DirectMessage.objects.filter(id__in=last_ids).select_related("sender", "recipient").order_by("-created_at")
    }
    for conversation in conversations:
        conversation.other_user = conversation.other_for(request.user)
        conversation.is_selected = False
        try:
            conversation.other_user_is_online = bool(conversation.other_user.presence.is_online)
        except Exception:
            conversation.other_user_is_online = False
        conversation.last_message = last_messages.get(conversation.last_message_id)
        if conversation.last_message:
            try:
                conversation.last_preview = conversation.last_message.get_body()[:120]
            except Exception:
                conversation.last_preview = "[encrypted message]"
        else:
            conversation.last_preview = "No messages yet."

    activity_notifications = list(
        request.user.notifications.select_related("actor", "thread", "post", "chat_room", "chat_message", "actor__presence").order_by("-created_at")[:50]
    )
    for notification in activity_notifications:
        if notification.thread:
            destination_url = notification.thread.get_absolute_url()
            if notification.post_id:
                destination_url = f"{destination_url}#post-{notification.post_id}"
            notification.destination_url = destination_url
        elif notification.chat_room:
            destination_url = notification.chat_room.get_absolute_url()
            if notification.chat_message_id:
                destination_url = f"{destination_url}#chat-message-{notification.chat_message_id}"
            notification.destination_url = destination_url
        else:
            notification.destination_url = ""
        try:
            notification.actor_is_online = bool(notification.actor and notification.actor.presence.is_online)
        except Exception:
            notification.actor_is_online = False

    selected_username = (request.GET.get("u") or "").strip().lstrip("@")

    target_user = None
    active_conversation = None
    target_accepts_dms = True
    dm_messages = []
    dm_form = DirectMessageForm()

    if selected_username:
        candidate = User.objects.filter(username__iexact=selected_username, is_active=True).select_related("presence").first()
        if candidate and candidate.id != request.user.id:
            target_user = candidate
            active_conversation = DirectConversation.for_users(request.user, target_user)
            target_accepts_dms = _incoming_dm_allowed(target_user)
            dm_messages = _decrypted_messages_for(request.user, active_conversation)
            dm_form.fields["body"].widget.attrs["placeholder"] = f"Message @{target_user.username}..."
            try:
                target_user.is_currently_online = bool(target_user.presence.is_online)
            except Exception:
                target_user.is_currently_online = False

    for conversation in conversations:
        conversation.is_selected = bool(target_user and conversation.other_user.username == target_user.username)

    return render(
        request,
        "dm/inbox.html",
        {
            "conversations": conversations,
            "activity_notifications": activity_notifications,
            "selected_dm_username": target_user.username if target_user else "",
            "target_user": target_user,
            "conversation": active_conversation,
            "target_accepts_dms": target_accepts_dms,
            "dm_messages": dm_messages,
            "form": dm_form,
            "report_form": ReportDirectMessageForm(),
            "start_form": StartDirectMessageForm(),
        },
    )


@login_required
@rate_limit(key_prefix="dm_conversation", max_ip_hits=120, max_user_hits=80, window_seconds=60)
def dm_conversation(request: HttpRequest, username: str) -> HttpResponse:
    target = _target_user_or_404(request.user, username)
    inbox_url = f"{reverse('dm:inbox')}?u={target.username}"
    if request.method == "GET":
        return redirect(inbox_url)

    target_accepts_dms = _incoming_dm_allowed(target)
    conversation = DirectConversation.for_users(request.user, target)

    form = DirectMessageForm(request.POST, request.FILES)
    if not target_accepts_dms:
        messages.error(request, f"@{target.username} has incoming DMs disabled.")
        return redirect(inbox_url)
    if form.is_valid():
        _send_dm(conversation, request.user, target, form.cleaned_data["body"], form.cleaned_data.get("attachments"))
        return redirect(inbox_url)
    messages.error(request, "Could not send DM. Please review the form.")
    return redirect(inbox_url)


@login_required
@require_POST
@rate_limit(key_prefix="dm_quick_send", max_ip_hits=120, max_user_hits=80, window_seconds=60)
def quick_dm_send(request: HttpRequest, username: str) -> HttpResponse:
    target = _target_user_or_404(request.user, username)
    fallback_url = reverse("dm:conversation", kwargs={"username": target.username})
    next_url = _safe_next_url(request, fallback=fallback_url)
    form = QuickDirectMessageForm(request.POST)

    if not _incoming_dm_allowed(target):
        messages.error(request, f"@{target.username} has incoming DMs disabled.")
        return redirect(next_url)
    if not form.is_valid():
        messages.error(request, "Could not send DM. Please enter a message.")
        return redirect(next_url)

    conversation = DirectConversation.for_users(request.user, target)
    _send_dm(conversation, request.user, target, form.cleaned_data["body"])
    messages.success(request, f"DM sent to @{target.username}.")
    return redirect(next_url)


@login_required
@require_POST
@rate_limit(key_prefix="dm_start", max_ip_hits=120, max_user_hits=80, window_seconds=60)
def start_dm(request: HttpRequest) -> HttpResponse:
    form = StartDirectMessageForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Could not start DM. Enter a valid username and message.")
        return redirect("dm:inbox")

    username = form.cleaned_data["username"]
    target = User.objects.filter(username__iexact=username, is_active=True).first()
    if not target:
        messages.error(request, f"User @{username} was not found.")
        return redirect("dm:inbox")
    if target.id == request.user.id:
        messages.error(request, "You cannot DM yourself.")
        return redirect("dm:inbox")
    if not _incoming_dm_allowed(target):
        messages.error(request, f"@{target.username} has incoming DMs disabled.")
        return redirect("dm:inbox")

    conversation = DirectConversation.for_users(request.user, target)
    _send_dm(conversation, request.user, target, form.cleaned_data["body"], form.cleaned_data.get("attachments"))
    return redirect(f"{reverse('dm:inbox')}?u={target.username}")


@login_required
@rate_limit(key_prefix="dm_settings", max_ip_hits=80, max_user_hits=60, window_seconds=60)
def dm_settings(request: HttpRequest) -> HttpResponse:
    preference = DirectMessagePreference.for_user(request.user)
    if request.method == "POST":
        form = DirectMessagePreferenceForm(request.POST)
        if form.is_valid():
            preference.allow_incoming = form.cleaned_data["allow_incoming"]
            preference.save(update_fields=["allow_incoming", "updated_at"])
            messages.success(request, "DM settings updated.")
            return redirect("dm:settings")
    else:
        form = DirectMessagePreferenceForm(initial={"allow_incoming": preference.allow_incoming})
    return render(request, "dm/settings.html", {"preference_form": form})


@login_required
@require_POST
@rate_limit(key_prefix="dm_report", max_ip_hits=40, max_user_hits=20, window_seconds=60)
def report_dm_message(request: HttpRequest, message_id: int) -> HttpResponse:
    message_obj = get_object_or_404(
        DirectMessage.objects.select_related("conversation", "sender", "recipient"),
        id=message_id,
    )
    if request.user.id not in {
        message_obj.conversation.user_low_id,
        message_obj.conversation.user_high_id,
    }:
        raise Http404("Not allowed")
    form = ReportDirectMessageForm(request.POST)
    if form.is_valid():
        message_obj.mark_reported(request.user, form.cleaned_data.get("reason", ""))
        message_obj.save(update_fields=["is_reported", "report_reason", "reported_by", "reported_at"])
        messages.success(request, "DM reported for admin review.")
    return redirect("dm:conversation", username=message_obj.sender.username if message_obj.sender_id != request.user.id else message_obj.recipient.username)


@login_required
@user_passes_test(lambda user: user.is_staff)
def reported_dm_queue(request: HttpRequest) -> HttpResponse:
    reported = list(
        DirectMessage.objects.filter(is_reported=True)
        .select_related("conversation", "sender", "recipient", "reported_by")
        .prefetch_related("attachments")
        .order_by("-reported_at", "-created_at")[:200]
    )
    for message in reported:
        try:
            message.body_plain = message.get_body()
        except Exception:
            message.body_plain = "[encrypted message]"
    return render(request, "dm/reported_queue.html", {"reported_messages": reported})
