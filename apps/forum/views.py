import json
import time
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import DetailView, ListView, TemplateView

from apps.core.context_processors import invalidate_notification_count
from apps.core.ratelimit import rate_limit
from apps.forum.forms import PostForm, ThreadForm
from apps.forum.models import (
    Attachment,
    Category,
    ChatMessage,
    Mention,
    ModerationLog,
    ModerationWarning,
    Notification,
    Post,
    Report,
    ReputationGrant,
    Thread,
    Vote,
    extract_mentions,
)
from apps.forum.stats import (
    apply_user_forum_stats,
    build_user_forum_stats,
    granted_post_reputation_ids,
    granted_thread_reputation_ids,
)

User = get_user_model()


def build_post_tree(posts):
    post_list = list(posts)
    children_map = {post.id: [] for post in post_list}
    visible_ids = {post.id for post in post_list}
    roots = []

    for post in post_list:
        if post.parent_id and post.parent_id in visible_ids:
            children_map[post.parent_id].append(post)
        else:
            roots.append(post)

    def attach_children(items, depth=0):
        nodes = []
        for item in items:
            nodes.append(
                {
                    "post": item,
                    "depth": depth,
                    "children": attach_children(children_map[item.id], depth + 1),
                }
            )
        return nodes

    return attach_children(roots)


def role_rank(user) -> int:
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return 0
    prefetched = getattr(user, "_prefetched_objects_cache", {}).get("groups")
    if prefetched is not None:
        names = {group.name for group in prefetched}
    else:
        names = set(user.groups.values_list("name", flat=True))
    if "Admin" in names:
        return 0
    if "Moderator" in names:
        return 1
    return 2


def mentionable_users_payload() -> list[dict[str, str]]:
    cached = cache.get("mentionable_users_v1")
    if cached is not None:
        return cached
    users = (
        User.objects.filter(is_active=True)
        .order_by("username")
        .only("username", "avatar")[:100]
    )
    payload = [
        {
            "username": user.username,
            "avatar_url": user.avatar.url if user.avatar else "",
        }
        for user in users
    ]
    cache.set("mentionable_users_v1", payload, timeout=60)
    return payload


def thread_unread_mention_counts(user, thread_ids: list[int]) -> dict[int, int]:
    if not getattr(user, "is_authenticated", False) or not thread_ids:
        return {}
    rows = (
        Notification.objects.filter(
            recipient=user,
            kind="mention",
            is_read=False,
            thread_id__in=thread_ids,
        )
        .values("thread_id")
        .annotate(total=Count("id"))
    )
    return {row["thread_id"]: row["total"] for row in rows}


def apply_thread_mention_state(user, threads):
    thread_list = list(threads)
    mention_counts = thread_unread_mention_counts(user, [thread.id for thread in thread_list])
    for thread in thread_list:
        thread.unread_mention_count = mention_counts.get(thread.id, 0)
        thread.has_unread_mentions = thread.unread_mention_count > 0
    return thread_list


def _delete_attachment_files(file_names: list[str]) -> None:
    for file_name in {name for name in file_names if name}:
        default_storage.delete(file_name)


def permanently_delete_thread(thread: Thread, actor, note: str = "") -> None:
    post_ids = list(thread.posts.values_list("id", flat=True))
    attachment_files = list(
        Attachment.objects.filter(post__thread=thread)
        .exclude(file="")
        .values_list("file", flat=True)
    )

    with transaction.atomic():
        Report.objects.filter(
            Q(target_type="thread", target_id=thread.id)
            | Q(target_type="post", target_id__in=post_ids)
        ).delete()
        Vote.objects.filter(
            Q(target_type="thread", target_id=thread.id)
            | Q(target_type="post", target_id__in=post_ids)
        ).delete()
        thread_id = thread.id
        thread.delete()
        ModerationLog.objects.create(
            actor=actor,
            action="hard_delete",
            target_type="thread",
            target_id=thread_id,
            notes=note,
        )
        transaction.on_commit(lambda: _delete_attachment_files(attachment_files))


def get_thread_lead_image_post(thread: Thread):
    return (
        thread.posts.filter(author_id=thread.author_id, parent__isnull=True, body_markdown="")
        .annotate(attachment_count=Count("attachments"))
        .filter(attachment_count__gt=0)
        .prefetch_related("attachments")
        .order_by("created_at")
        .first()
    )


def categories_with_hot_threads(user=None, limit_per_category: int = 4):
    categories = list(
        Category.objects.filter(is_public=True)
        .annotate(thread_count=Count("threads", filter=Q(threads__is_deleted=False)))
        .order_by("name")
    )
    since = timezone.now() - timedelta(hours=24)
    max_threads = max(1, limit_per_category * max(1, len(categories)))
    hot_list = list(
        Thread.objects.filter(is_deleted=False, updated_at__gte=since)
        .select_related("category")
        .only("id", "title", "category_id", "created_at", "updated_at")
        .annotate(reply_count=Count("posts", filter=Q(posts__is_deleted=False)))
        .order_by("-updated_at")[:max_threads]
    )
    by_category: dict[int, list[Thread]] = {}
    for thread in hot_list:
        thread.unread_mention_count = 0
        thread.has_unread_mentions = False
        bucket = by_category.setdefault(thread.category_id, [])
        if len(bucket) < limit_per_category:
            bucket.append(thread)
    for category in categories:
        category.active_threads_24h = by_category.get(category.id, [])
    return categories


class HomeView(ListView):
    template_name = "forum/home.html"
    context_object_name = "threads"
    paginate_by = 20

    def get_queryset(self):
        query = self.request.GET.get("q", "").strip()
        category_slug = self.request.GET.get("category", "").strip()
        qs = (
            Thread.objects.filter(is_deleted=False)
            .select_related("author", "category")
            .prefetch_related("tags")
            .annotate(reply_count=Count("posts", filter=Q(posts__is_deleted=False)))
            .order_by("-updated_at", "-created_at")
        )
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        if query:
            qs = qs.filter(Q(title__icontains=query) | Q(body_markdown__icontains=query))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["threads"] = apply_thread_mention_state(self.request.user, context["threads"])
        category_slug = self.request.GET.get("category", "").strip()
        context["categories"] = categories_with_hot_threads(self.request.user)
        context["announcements"] = apply_thread_mention_state(
            self.request.user,
            (
                Thread.objects.filter(is_deleted=False, is_announcement=True)
                .select_related("author", "category")
                .annotate(reply_count=Count("posts", filter=Q(posts__is_deleted=False)))
            )[:5],
        )
        context["recent_threads"] = apply_thread_mention_state(
            self.request.user,
            (
                Thread.objects.filter(is_deleted=False)
                .select_related("author", "category")
                .annotate(reply_count=Count("posts", filter=Q(posts__is_deleted=False)))
            )[:8],
        )
        context["active_category_slug"] = category_slug
        context["q"] = self.request.GET.get("q", "")
        return context


class ThreadDetailView(DetailView):
    template_name = "forum/thread_detail.html"
    context_object_name = "thread"
    model = Thread
    pk_url_kwarg = "thread_id"

    def get_queryset(self):
        return Thread.objects.select_related("author", "category").prefetch_related("tags", "author__groups")

    def get_object(self, queryset=None):
        obj = super().get_object(queryset=queryset)
        if obj.is_deleted and not self.request.user.has_perm("forum.change_thread"):
            raise Http404("Thread not found.")
        return obj

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        canonical_url = self.object.get_absolute_url()
        if request.path != canonical_url:
            return redirect(canonical_url, permanent=True)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["canonical_url"] = self.request.build_absolute_uri(self.object.get_absolute_url())
        if self.request.user.is_authenticated:
            marked_read = Notification.objects.filter(
                recipient=self.request.user,
                kind="mention",
                thread=self.object,
                is_read=False,
            ).update(is_read=True)
            if marked_read:
                invalidate_notification_count(self.request.user.id)
        lead_image_post = get_thread_lead_image_post(self.object)
        posts = (
            self.object.posts.select_related("author", "parent", "parent__author")
            .prefetch_related("attachments", "author__groups", "parent__author__groups")
        )
        if lead_image_post:
            posts = posts.exclude(id=lead_image_post.id)
        if not self.request.user.has_perm("forum.change_post"):
            posts = posts.filter(is_deleted=False)
        post_list = list(posts)
        context["thread_lead_attachments"] = list(lead_image_post.attachments.all()) if lead_image_post else []
        context["posts"] = post_list
        context["post_tree"] = build_post_tree(post_list)
        context["categories"] = categories_with_hot_threads(self.request.user)
        context["related_threads"] = (
            Thread.objects.filter(category=self.object.category, is_deleted=False)
            .exclude(id=self.object.id)
            .select_related("author")
            .annotate(reply_count=Count("posts", filter=Q(posts__is_deleted=False)))
        )[:8]
        all_participant_ids = list({post.author_id for post in post_list})
        if self.object.author_id not in all_participant_ids:
            all_participant_ids.append(self.object.author_id)

        user_stats = build_user_forum_stats(all_participant_ids)
        granted_post_ids = granted_post_reputation_ids(self.request.user, [post.id for post in post_list])
        granted_thread_ids = granted_thread_reputation_ids(self.request.user, [self.object.id])

        latest_replier_ids: list[int] = []
        seen_repliers: set[int] = set()
        for post in reversed(post_list):
            author_id = post.author_id
            if author_id == self.object.author_id or author_id in seen_repliers:
                continue
            seen_repliers.add(author_id)
            latest_replier_ids.append(author_id)

        participant_limit = 15
        sidebar_participant_ids = [self.object.author_id, *latest_replier_ids[: participant_limit - 1]]
        participant_total_count = len(all_participant_ids)

        participants_by_id = {
            user.id: user
            for user in User.objects.filter(id__in=sidebar_participant_ids)
            .select_related("presence")
            .prefetch_related("groups")
        }
        participants = [participants_by_id[user_id] for user_id in sidebar_participant_ids if user_id in participants_by_id]

        for participant in participants:
            participant.is_currently_online = hasattr(participant, "presence") and participant.presence.is_online
            participant.is_thread_author = participant.id == self.object.author_id
            apply_user_forum_stats(participant, user_stats)
        apply_user_forum_stats(self.object.author, user_stats)
        self.object.user_has_given_rep = self.object.id in granted_thread_ids
        self.object.can_receive_rep = (
            self.request.user.is_authenticated
            and self.request.user.id != self.object.author_id
            and not self.object.user_has_given_rep
        )
        self.object.can_warn_author = self.request.user.has_perm("forum.change_post") and self.request.user.id != self.object.author_id
        for post in post_list:
            apply_user_forum_stats(post.author, user_stats)
            post.user_has_given_rep = post.id in granted_post_ids
            post.can_receive_rep = (
                self.request.user.is_authenticated and self.request.user.id != post.author_id and not post.user_has_given_rep
            )
            post.can_warn_author = self.request.user.has_perm("forum.change_post") and self.request.user.id != post.author_id
        context["thread_participants"] = participants
        context["participant_count"] = participant_total_count
        context["reply_count"] = len(post_list)
        context["post_form"] = PostForm()
        context["thread_votes"] = vote_total("thread", self.object.id)
        context["can_moderate"] = self.request.user.has_perm("forum.change_post")
        context["mentionable_users"] = mentionable_users_payload()
        return context


def thread_legacy_redirect(request: HttpRequest, thread_id: int) -> HttpResponse:
    thread = get_object_or_404(Thread, id=thread_id, is_deleted=False)
    return redirect(thread.get_absolute_url(), permanent=True)


@login_required
@permission_required("forum.add_thread", raise_exception=True)
@rate_limit(key_prefix="thread_create", max_ip_hits=30, max_user_hits=20, window_seconds=60)
def thread_create(request: HttpRequest) -> HttpResponse:
    category_slug = (request.GET.get("category") or "").strip()
    initial_category = None
    if category_slug:
        initial_category = Category.objects.filter(slug=category_slug, is_public=True).first()
    if request.method == "POST":
        form = ThreadForm(request.POST, request.FILES)
        if form.is_valid():
            thread = form.save(commit=False)
            thread.author = request.user
            thread.save()
            form.save_m2m()
            image = form.cleaned_data.get("attachment")
            if image:
                lead_image_post = Post.objects.create(
                    thread=thread,
                    author=request.user,
                    body_markdown="",
                )
                Attachment.objects.create(
                    post=lead_image_post,
                    file=image,
                    original_name=image.name,
                    mime_type=image.content_type or "",
                    size_bytes=image.size,
                )
            mentioned_usernames = extract_mentions(thread.body_markdown)
            if mentioned_usernames:
                mentioned_users = User.objects.filter(username__in=mentioned_usernames).exclude(id=request.user.id)
                Notification.objects.bulk_create(
                    [
                        Notification(
                            recipient=user,
                            actor=request.user,
                            kind="mention",
                            thread=thread,
                            body=f"{request.user.username} mentioned you in a new thread",
                        )
                        for user in mentioned_users
                    ]
                )
                invalidate_notification_count(*(user.id for user in mentioned_users))
            messages.success(request, "Thread created.")
            return redirect(thread)
    else:
        form = ThreadForm(initial={"category": initial_category} if initial_category else None)
    return render(
        request,
        "forum/thread_create.html",
        {
            "form": form,
            "mentionable_users": mentionable_users_payload(),
            "selected_category": initial_category,
        },
    )


@login_required
@require_POST
@permission_required("forum.add_post", raise_exception=True)
@rate_limit(key_prefix="post_reply", max_ip_hits=50, max_user_hits=25, window_seconds=60)
def post_reply(request: HttpRequest, thread_id: int) -> HttpResponse:
    thread = get_object_or_404(Thread, id=thread_id, is_deleted=False)
    if thread.is_locked and not request.user.has_perm("forum.change_post"):
        raise Http404("Thread is locked.")
    form = PostForm(request.POST, request.FILES)
    if form.is_valid():
        post = form.save(commit=False)
        post.thread = thread
        post.author = request.user
        try:
            parent_id = int(request.POST.get("parent_id", "0") or 0)
        except ValueError:
            parent_id = 0
        if parent_id:
            parent = Post.objects.filter(id=parent_id, thread=thread).first()
            if parent:
                post.parent = parent
        post.save()
        file = form.cleaned_data.get("attachment")
        if file:
            Attachment.objects.create(
                post=post,
                file=file,
                original_name=file.name,
                mime_type=file.content_type or "",
                size_bytes=file.size,
            )

        mentioned_usernames = extract_mentions(post.body_markdown)
        mentioned_ids: list[int] = []
        notification_recipient_ids: set[int] = set()
        if mentioned_usernames:
            mentioned_users = list(User.objects.filter(username__in=mentioned_usernames))
            mentioned_ids = [u.id for u in mentioned_users if u.id != request.user.id]
            Mention.objects.bulk_create(
                [Mention(post=post, mentioned_user=user) for user in mentioned_users],
                ignore_conflicts=True,
            )
            Notification.objects.bulk_create(
                [
                    Notification(
                        recipient=user,
                        actor=request.user,
                        kind="mention",
                        thread=thread,
                        post=post,
                        body=f"{request.user.username} mentioned you in a reply",
                    )
                    for user in mentioned_users
                    if user.id != request.user.id
                ]
            )
            notification_recipient_ids.update(mentioned_ids)

        notified_reply_targets = {request.user.id, *mentioned_ids}
        if post.parent_id and post.parent and post.parent.author_id not in notified_reply_targets:
            Notification.objects.create(
                recipient=post.parent.author,
                actor=request.user,
                kind="reply",
                thread=thread,
                post=post,
                body=f"{request.user.username} replied to your post",
            )
            notified_reply_targets.add(post.parent.author_id)
            notification_recipient_ids.add(post.parent.author_id)

        if thread.author_id not in notified_reply_targets:
            Notification.objects.create(
                recipient=thread.author,
                actor=request.user,
                kind="reply",
                thread=thread,
                post=post,
                body=f"{request.user.username} replied to your thread",
            )
            notification_recipient_ids.add(thread.author_id)

        thread.updated_at = timezone.now()
        thread.save(update_fields=["updated_at"])
        invalidate_notification_count(*notification_recipient_ids)
        messages.success(request, "Reply posted.")
    else:
        messages.error(request, "Could not post reply. Please review the form.")
    return redirect(thread)


@login_required
@rate_limit(key_prefix="post_edit", max_ip_hits=50, max_user_hits=20, window_seconds=60)
def edit_post(request: HttpRequest, post_id: int) -> HttpResponse:
    post = get_object_or_404(Post, id=post_id)
    if post.is_deleted:
        raise Http404("Post not found.")
    if post.author_id != request.user.id and not request.user.has_perm("forum.change_post"):
        raise Http404("Not allowed.")
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            post = form.save(commit=False)
            post.edited_at = timezone.now()
            post.save(update_fields=["body_markdown", "edited_at"])
            messages.success(request, "Reply updated.")
            return redirect(post.thread)
    else:
        form = PostForm(instance=post)
    return render(
        request,
        "forum/post_edit.html",
        {"form": form, "post": post, "mentionable_users": mentionable_users_payload()},
    )


def redirect_to_safe_next(request: HttpRequest, fallback) -> HttpResponse:
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    referer = (request.META.get("HTTP_REFERER") or "").strip()
    if referer and url_has_allowed_host_and_scheme(referer, {request.get_host()}, require_https=request.is_secure()):
        return redirect(referer)
    return redirect(fallback)


@login_required
@require_POST
@permission_required("forum.add_vote", raise_exception=True)
@rate_limit(key_prefix="vote", max_ip_hits=80, max_user_hits=40, window_seconds=60)
def vote(request: HttpRequest) -> JsonResponse:
    target_type = request.POST.get("target_type", "")
    try:
        target_id = int(request.POST.get("target_id", "0"))
        value = int(request.POST.get("value", "0"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False}, status=400)
    if target_type not in {"thread", "post"} or value not in {-1, 1} or target_id <= 0:
        return JsonResponse({"ok": False}, status=400)
    Vote.objects.update_or_create(
        target_type=target_type,
        target_id=target_id,
        user=request.user,
        defaults={"value": value},
    )
    return JsonResponse({"ok": True, "score": vote_total(target_type, target_id)})


@login_required
@require_POST
@rate_limit(key_prefix="rep_grant", max_ip_hits=80, max_user_hits=40, window_seconds=60)
def grant_reputation(request: HttpRequest) -> HttpResponse:
    target_type = request.POST.get("target_type", "")
    try:
        target_id = int(request.POST.get("target_id", "0") or 0)
    except (TypeError, ValueError):
        target_id = 0

    if target_type == "thread" and target_id > 0:
        thread = get_object_or_404(Thread, id=target_id, is_deleted=False)
        if request.user.id == thread.author_id:
            messages.error(request, "You cannot give rep to your own thread.")
            return redirect_to_safe_next(request, thread)
        _, created = ReputationGrant.objects.get_or_create(
            actor=request.user,
            thread=thread,
            defaults={"recipient": thread.author},
        )
        if created:
            messages.success(request, f"You gave +rep to {thread.author.username}.")
        else:
            messages.info(request, "You already gave rep on this thread.")
        return redirect_to_safe_next(request, thread)

    if target_type == "post" and target_id > 0:
        post = get_object_or_404(Post.objects.select_related("thread", "author"), id=target_id, is_deleted=False)
        if request.user.id == post.author_id:
            messages.error(request, "You cannot give rep to your own post.")
            return redirect_to_safe_next(request, post.thread)
        _, created = ReputationGrant.objects.get_or_create(
            actor=request.user,
            post=post,
            defaults={"recipient": post.author},
        )
        if created:
            messages.success(request, f"You gave +rep to {post.author.username}.")
        else:
            messages.info(request, "You already gave rep on this post.")
        return redirect_to_safe_next(request, post.thread)

    raise Http404("Invalid reputation target")


@login_required
@permission_required("forum.change_post", raise_exception=True)
@require_POST
@rate_limit(key_prefix="mod_warn", max_ip_hits=40, max_user_hits=20, window_seconds=60)
def warn_user(request: HttpRequest) -> HttpResponse:
    target_type = request.POST.get("target_type", "")
    note = request.POST.get("note", "").strip()[:200]
    try:
        target_id = int(request.POST.get("target_id", "0") or 0)
    except (TypeError, ValueError):
        target_id = 0

    if target_type == "thread" and target_id > 0:
        thread = get_object_or_404(Thread.objects.select_related("author"), id=target_id)
        warned_user = thread.author
        if warned_user.id == request.user.id:
            messages.error(request, "You cannot warn yourself.")
            return redirect_to_safe_next(request, thread)
        warning = ModerationWarning.objects.create(
            moderator=request.user,
            user=warned_user,
            thread=thread,
            reason=note or "Moderator warning",
        )
        redirect_target = thread
        moderation_target = ("thread", thread.id)
    elif target_type == "post" and target_id > 0:
        post = get_object_or_404(Post.objects.select_related("thread", "author"), id=target_id)
        warned_user = post.author
        if warned_user.id == request.user.id:
            messages.error(request, "You cannot warn yourself.")
            return redirect_to_safe_next(request, post.thread)
        warning = ModerationWarning.objects.create(
            moderator=request.user,
            user=warned_user,
            post=post,
            thread=post.thread,
            reason=note or "Moderator warning",
        )
        redirect_target = post.thread
        moderation_target = ("post", post.id)
    elif target_type == "chat_message" and target_id > 0:
        chat_message = get_object_or_404(ChatMessage.objects.select_related("room", "author"), id=target_id)
        warned_user = chat_message.author
        if warned_user.id == request.user.id:
            messages.error(request, "You cannot warn yourself.")
            return redirect_to_safe_next(request, chat_message.room.get_absolute_url())
        warning = ModerationWarning.objects.create(
            moderator=request.user,
            user=warned_user,
            chat_message=chat_message,
            reason=note or "Moderator warning",
        )
        redirect_target = chat_message.room.get_absolute_url()
        moderation_target = ("chat_message", chat_message.id)
    else:
        raise Http404("Invalid warning target")

    Notification.objects.create(
        recipient=warned_user,
        actor=request.user,
        kind="system",
        thread=warning.thread,
        post=warning.post,
        chat_room=getattr(getattr(warning, "chat_message", None), "room", None),
        chat_message=warning.chat_message,
        body=f"You were warned by a moderator and lost {warning.rep_penalty} rep.",
    )
    invalidate_notification_count(warned_user.id)
    ModerationLog.objects.create(
        actor=request.user,
        action="warn_user",
        target_type=moderation_target[0],
        target_id=moderation_target[1],
        notes=warning.reason,
    )
    messages.success(request, f"{warned_user.username} warned. -{warning.rep_penalty} rep applied.")
    return redirect_to_safe_next(request, redirect_target)


@login_required
@require_POST
@permission_required("forum.add_report", raise_exception=True)
@rate_limit(key_prefix="report", max_ip_hits=30, max_user_hits=12, window_seconds=60)
def report_content(request: HttpRequest) -> HttpResponse:
    target_type = request.POST.get("target_type", "")
    try:
        target_id = int(request.POST.get("target_id", "0"))
    except (TypeError, ValueError):
        target_id = 0
    reason = request.POST.get("reason", "").strip()[:200]
    details = request.POST.get("details", "").strip()[:2000]
    if target_type not in {"thread", "post", "chat_message"} or target_id <= 0 or not reason:
        messages.error(request, "Invalid report request.")
        return redirect("forum:home")
    Report.objects.create(
        reporter=request.user,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        details=details,
    )
    messages.success(request, "Report submitted.")
    safe_next = request.META.get("HTTP_REFERER", "")
    if safe_next and url_has_allowed_host_and_scheme(safe_next, {request.get_host()}, require_https=request.is_secure()):
        return redirect(safe_next)
    return redirect("forum:home")


class ModerationQueueView(TemplateView):
    template_name = "forum/moderation_queue.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perm("forum.change_report"):
            raise Http404("Not allowed")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["reports"] = Report.objects.select_related("reporter", "handled_by")
        context["logs"] = ModerationLog.objects.select_related("actor")[:150]
        return context


@login_required
@permission_required("forum.change_report", raise_exception=True)
@require_POST
def moderate_report(request: HttpRequest, report_id: int) -> HttpResponse:
    report = get_object_or_404(Report, id=report_id)
    action = request.POST.get("action", "")
    now = timezone.now()
    if action == "resolve":
        report.status = "resolved"
        moderation_action = "report_resolve"
    else:
        report.status = "dismissed"
        moderation_action = "report_dismiss"
    report.handled_by = request.user
    report.handled_at = now
    report.save(update_fields=["status", "handled_by", "handled_at"])
    ModerationLog.objects.create(
        actor=request.user,
        action=moderation_action,
        target_type="report",
        target_id=report.id,
        notes=f"{report.target_type}:{report.target_id}",
    )
    return redirect("forum:moderation_queue")


@login_required
@permission_required("forum.change_post", raise_exception=True)
@require_POST
def soft_delete_target(request: HttpRequest) -> HttpResponse:
    target_type = request.POST.get("target_type", "")
    try:
        target_id = int(request.POST.get("target_id", "0") or 0)
    except (TypeError, ValueError):
        raise Http404("Invalid target")
    note = request.POST.get("note", "").strip()[:200]
    now = timezone.now()
    if target_type == "thread":
        thread = get_object_or_404(Thread, id=target_id)
        thread.is_deleted = True
        thread.deleted_at = now
        thread.deleted_by = request.user
        thread.deletion_reason = note or "moderator_action"
        thread.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
        target_key = "thread"
        fallback_url = thread.get_absolute_url()
    elif target_type == "post":
        post = get_object_or_404(Post, id=target_id)
        post.is_deleted = True
        post.deleted_at = now
        post.deleted_by = request.user
        post.deletion_reason = note or "moderator_action"
        post.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
        target_key = "post"
        fallback_url = post.thread.get_absolute_url()
    elif target_type == "chat_message":
        chat_message = get_object_or_404(ChatMessage, id=target_id)
        chat_message.is_deleted = True
        chat_message.deleted_at = now
        chat_message.deleted_by = request.user
        chat_message.deletion_reason = note or "moderator_action"
        chat_message.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
        target_key = "chat_message"
        fallback_url = f"{chat_message.room.get_absolute_url()}#chat-message-{chat_message.id}"
    else:
        raise Http404("Invalid target")
    ModerationLog.objects.create(
        actor=request.user,
        action="soft_delete",
        target_type=target_key,
        target_id=target_id,
        notes=note,
    )
    messages.success(request, f"{target_key} soft-deleted.")
    return redirect_to_safe_next(request, fallback_url)


@login_required
@permission_required("forum.delete_thread", raise_exception=True)
@require_POST
def hard_delete_thread(request: HttpRequest, thread_id: int) -> HttpResponse:
    thread = get_object_or_404(Thread, id=thread_id)
    note = request.POST.get("note", "").strip()[:200]
    title = thread.title
    permanently_delete_thread(thread, request.user, note=note or "admin_nuke")
    messages.success(request, f'Thread "{title}" permanently deleted.')
    return redirect("forum:home")


@login_required
@permission_required("forum.change_post", raise_exception=True)
@require_POST
def restore_target(request: HttpRequest) -> HttpResponse:
    target_type = request.POST.get("target_type", "")
    try:
        target_id = int(request.POST.get("target_id", "0") or 0)
    except (TypeError, ValueError):
        raise Http404("Invalid target")
    if target_type == "thread":
        thread = get_object_or_404(Thread, id=target_id)
        thread.is_deleted = False
        thread.deleted_at = None
        thread.deleted_by = None
        thread.deletion_reason = ""
        thread.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
        target_key = "thread"
        fallback_url = thread.get_absolute_url()
    elif target_type == "post":
        post = get_object_or_404(Post, id=target_id)
        post.is_deleted = False
        post.deleted_at = None
        post.deleted_by = None
        post.deletion_reason = ""
        post.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
        target_key = "post"
        fallback_url = post.thread.get_absolute_url()
    elif target_type == "chat_message":
        chat_message = get_object_or_404(ChatMessage, id=target_id)
        chat_message.is_deleted = False
        chat_message.deleted_at = None
        chat_message.deleted_by = None
        chat_message.deletion_reason = ""
        chat_message.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "deletion_reason"])
        target_key = "chat_message"
        fallback_url = f"{chat_message.room.get_absolute_url()}#chat-message-{chat_message.id}"
    else:
        raise Http404("Invalid target")
    ModerationLog.objects.create(
        actor=request.user,
        action="restore",
        target_type=target_key,
        target_id=target_id,
    )
    messages.success(request, f"{target_key} restored.")
    return redirect_to_safe_next(request, fallback_url)


@login_required
@permission_required("forum.change_thread", raise_exception=True)
@require_POST
def set_thread_flag(request: HttpRequest, thread_id: int) -> HttpResponse:
    thread = get_object_or_404(Thread, id=thread_id)
    flag = request.POST.get("flag", "")
    value = request.POST.get("value", "0") == "1"
    if flag not in {"is_pinned", "is_announcement", "is_locked"}:
        raise Http404("Unknown flag")
    setattr(thread, flag, value)
    thread.save(update_fields=[flag, "updated_at"])
    ModerationLog.objects.create(
        actor=request.user,
        action="thread_flag",
        target_type="thread",
        target_id=thread.id,
        notes=f"flag:{flag} value:{value}",
    )
    messages.success(request, "Thread setting updated.")
    return redirect(thread)


@require_GET
def thread_posts_partial(request: HttpRequest, thread_id: int) -> HttpResponse:
    thread = get_object_or_404(Thread, id=thread_id, is_deleted=False)
    lead_image_post = get_thread_lead_image_post(thread)
    posts = (
        thread.posts.select_related("author", "parent", "parent__author")
        .prefetch_related("attachments", "author__groups", "parent__author__groups")
    )
    if lead_image_post:
        posts = posts.exclude(id=lead_image_post.id)
    if not request.user.has_perm("forum.change_post"):
        posts = posts.filter(is_deleted=False)
    post_list = list(posts)
    participant_ids = list({post.author_id for post in post_list})
    if thread.author_id not in participant_ids:
        participant_ids.append(thread.author_id)
    user_stats = build_user_forum_stats(participant_ids)
    granted_post_ids = granted_post_reputation_ids(request.user, [post.id for post in post_list])
    for post in post_list:
        apply_user_forum_stats(post.author, user_stats)
        post.user_has_given_rep = post.id in granted_post_ids
        post.can_receive_rep = request.user.is_authenticated and request.user.id != post.author_id and not post.user_has_given_rep
        post.can_warn_author = request.user.has_perm("forum.change_post") and request.user.id != post.author_id
    return render(
        request,
        "forum/partials/post_list.html",
        {"thread": thread, "posts": post_list, "post_tree": build_post_tree(post_list)},
    )


@require_GET
def thread_events(request: HttpRequest, thread_id: int) -> StreamingHttpResponse:
    thread = get_object_or_404(Thread, id=thread_id, is_deleted=False)
    last_seen = int(request.GET.get("last_seen", "0") or 0)

    def event_stream():
        current = last_seen
        for _ in range(60):
            latest_post = (
                Post.objects.filter(thread=thread, is_deleted=False).order_by("-id").values_list("id", flat=True).first() or 0
            )
            if latest_post > current:
                payload = {
                    "thread_id": thread.id,
                    "latest_post_id": latest_post,
                    "updated_at": thread.updated_at.isoformat(),
                }
                yield f"event: thread_update\ndata: {json.dumps(payload)}\n\n"
                current = latest_post
            else:
                yield "event: heartbeat\ndata: {}\n\n"
            time.sleep(2)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def vote_total(target_type: str, target_id: int) -> int:
    return Vote.objects.filter(target_type=target_type, target_id=target_id).aggregate(total=Sum("value"))["total"] or 0
