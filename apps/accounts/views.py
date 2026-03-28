import json
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, FormView, UpdateView
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.forms import CaptchaAwareAuthenticationForm, DeleteAccountForm, ProfileForm, SignUpForm
from apps.core.context_processors import get_unread_notification_count, invalidate_notification_count
from apps.core.models import LegalDocument, UserLegalConsent
from apps.core.ratelimit import rate_limit
from apps.dm.context_processors import get_dm_context_payload
from apps.dm.models import DirectMessagePreference
from apps.forum.models import ChatMessage, ModerationWarning, Notification, Post, ReputationGrant, Thread
from apps.forum.stats import apply_user_forum_stats, build_user_forum_stats

User = get_user_model()


@method_decorator(
    rate_limit(key_prefix="auth_login", max_ip_hits=25, max_user_hits=15, window_seconds=60), name="dispatch"
)
class CaptchaLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = CaptchaAwareAuthenticationForm


class CaptchaLogoutView(LogoutView):
    pass


@method_decorator(
    rate_limit(key_prefix="auth_register", max_ip_hits=15, max_user_hits=8, window_seconds=60), name="dispatch"
)
class SignUpView(FormView):
    template_name = "accounts/register.html"
    form_class = SignUpForm
    success_url = reverse_lazy("forum:home")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        user = form.save(commit=False)
        user.email = form.cleaned_data["email"]
        user.is_active = True
        user.save()
        member_group = Group.objects.filter(name="Member").first()
        if member_group:
            user.groups.add(member_group)
        terms = LegalDocument.objects.filter(doc_type="terms").first()
        privacy = LegalDocument.objects.filter(doc_type="privacy").first()
        UserLegalConsent.objects.create(
            user=user,
            terms_version=terms.version if terms else "v1",
            privacy_version=privacy.version if privacy else "v1",
            cookies_version="",
        )
        login(self.request, user)
        if settings.EMAIL_VERIFICATION_REQUIRED:
            messages.info(self.request, "Email verification is enabled but mailing integration is pending.")
        return super().form_valid(form)


class ProfileDetailView(DetailView):
    template_name = "accounts/profile.html"
    context_object_name = "profile_user"
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile_user = context["profile_user"]
        stats = build_user_forum_stats([profile_user.id])
        apply_user_forum_stats(profile_user, stats)
        recent_threads = list(
            Thread.objects.filter(author=profile_user, is_deleted=False)
            .select_related("category")
            .order_by("-updated_at", "-created_at")[:5]
        )
        recent_posts = list(
            Post.objects.filter(author=profile_user, is_deleted=False)
            .select_related("thread", "thread__category")
            .order_by("-created_at")[:5]
        )
        for post in recent_posts:
            post.permalink_url = f"{post.thread.get_absolute_url()}#post-{post.id}"
        context["recent_threads"] = recent_threads
        context["recent_posts"] = recent_posts
        context["chat_post_count"] = ChatMessage.objects.filter(author=profile_user, is_deleted=False).count()
        context["chat_posts_url"] = reverse("forum:user_chat_messages", kwargs={"username": profile_user.username})
        return context


class ProfileEditView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/profile_edit.html"
    form_class = ProfileForm
    success_url = reverse_lazy("forum:home")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Profile updated.")
        return super().form_valid(form)


def user_card_partial(request: HttpRequest, username: str) -> HttpResponse:
    profile_user = get_object_or_404(User, username=username)
    stats = build_user_forum_stats([profile_user.id])
    apply_user_forum_stats(profile_user, stats)
    try:
        is_online = bool(profile_user.presence.is_online)
    except Exception:
        is_online = False
    dm_pref = DirectMessagePreference.objects.filter(user=profile_user).values_list("allow_incoming", flat=True).first()
    can_receive_dms = True if dm_pref is None else bool(dm_pref)
    referer = (request.META.get("HTTP_REFERER") or "").strip()
    if url_has_allowed_host_and_scheme(
        referer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        popup_next_url = referer
    else:
        popup_next_url = reverse_lazy("forum:home")
    recent_threads = list(
        Thread.objects.filter(author=profile_user, is_deleted=False)
        .select_related("category")
        .order_by("-updated_at", "-created_at")[:3]
    )
    recent_posts = list(
        Post.objects.filter(author=profile_user, is_deleted=False)
        .select_related("thread", "thread__category")
        .order_by("-created_at")[:3]
    )
    for post in recent_posts:
        post.permalink_url = f"{post.thread.get_absolute_url()}#post-{post.id}"
    chat_post_count = ChatMessage.objects.filter(author=profile_user, is_deleted=False).count()
    return render(
        request,
        "components/user_card_popup.html",
        {
            "profile_user": profile_user,
            "profile_user_is_online": is_online,
            "profile_user_accepts_dms": can_receive_dms,
            "popup_next_url": popup_next_url,
            "recent_threads": recent_threads,
            "recent_posts": recent_posts,
            "chat_post_count": chat_post_count,
            "chat_posts_url": reverse("forum:user_chat_messages", kwargs={"username": profile_user.username}),
        },
    )


@login_required
@require_GET
@rate_limit(key_prefix="mention_lookup", max_ip_hits=120, max_user_hits=80, window_seconds=60)
def mention_candidates(request: HttpRequest) -> JsonResponse:
    query = request.GET.get("q", "").strip()
    users = User.objects.filter(is_active=True)
    if query:
        users = users.filter(username__icontains=query)
    users = users.order_by("username")[:10]
    return JsonResponse(
        {
            "results": [
                {
                    "username": user.username,
                    "avatar_url": user.avatar.url if user.avatar else "",
                }
                for user in users
            ]
        }
    )


class NotificationsView(LoginRequiredMixin, DetailView):
    template_name = "accounts/notifications.html"
    context_object_name = "profile_user"
    model = User

    def get(self, request, *args, **kwargs):
        return redirect(f"{reverse('dm:inbox')}#inbox-activity")

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        notifications = self.request.user.notifications.select_related("actor", "thread", "post")
        context["notifications"] = notifications[:100]
        return context


@require_POST
def mark_notification_read(request: HttpRequest, notification_id: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    invalidate_notification_count(request.user.id)
    next_url = (request.POST.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(f"{reverse('dm:inbox')}#inbox-activity")


@login_required
@require_GET
@rate_limit(key_prefix="shell_state", max_ip_hits=240, max_user_hits=180, window_seconds=60)
def shell_state(request: HttpRequest) -> JsonResponse:
    dm_payload = get_dm_context_payload(request.user)
    unread_notifications_count = get_unread_notification_count(request.user)
    unread_dm_count = dm_payload["unread_dm_count"]
    return JsonResponse(
        {
            "unread_dm_count": unread_dm_count,
            "unread_notifications_count": unread_notifications_count,
            "inbox_total": unread_dm_count + unread_notifications_count,
            "has_dm_access": dm_payload["has_dm_access"],
        }
    )


def export_personal_data(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    user = request.user
    payload = {
        "generated_at": timezone.now().isoformat(),
        "user": {
            "username": user.username,
            "email": user.email,
            "date_joined": user.date_joined.isoformat() if user.date_joined else "",
            "bio": user.bio,
            "website_url": user.website_url,
            "social_x": user.social_x,
            "social_discord": user.social_discord,
        },
        "threads": list(
            Thread.objects.filter(author=user).values("id", "title", "body_markdown", "created_at", "updated_at")
        ),
        "posts": list(Post.objects.filter(author=user).values("id", "thread_id", "body_markdown", "created_at", "edited_at")),
        "notifications": list(
            user.notifications.values("id", "kind", "body", "is_read", "created_at", "thread_id", "post_id", "chat_room_id", "chat_message_id")
        ),
        "chat_messages": list(
            ChatMessage.objects.filter(author=user).values("id", "room_id", "reply_to_id", "body_markdown", "gif_url", "created_at")
        ),
        "reputation_received": list(
            ReputationGrant.objects.filter(recipient=user).values("id", "actor_id", "thread_id", "post_id", "created_at")
        ),
        "warnings_received": list(
            ModerationWarning.objects.filter(user=user).values(
                "id", "moderator_id", "thread_id", "post_id", "chat_message_id", "reason", "rep_penalty", "created_at"
            )
        ),
    }
    body = json.dumps(payload, indent=2, default=str)
    response = HttpResponse(body, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="dchat-export-{user.username}.json"'
    return response


class DeleteAccountView(LoginRequiredMixin, FormView):
    template_name = "accounts/delete_account.html"
    form_class = DeleteAccountForm
    success_url = reverse_lazy("forum:home")

    def form_valid(self, form):
        user = self.request.user
        password = form.cleaned_data["password"]
        confirm_text = form.cleaned_data["confirm_text"].strip().upper()
        if not user.check_password(password) or confirm_text != "DELETE":
            messages.error(self.request, "Deletion confirmation failed.")
            return self.form_invalid(form)

        if form.cleaned_data["delete_content"]:
            now = timezone.now()
            Thread.objects.filter(author=user, is_deleted=False).update(
                is_deleted=True,
                deleted_at=now,
                deletion_reason="user_requested",
                body_markdown="[deleted by user request]",
            )
            Post.objects.filter(author=user, is_deleted=False).update(
                is_deleted=True,
                deleted_at=now,
                deletion_reason="user_requested",
                body_markdown="[deleted by user request]",
            )
            ChatMessage.objects.filter(author=user, is_deleted=False).update(
                is_deleted=True,
                deleted_at=now,
                deletion_reason="user_requested",
                body_markdown="[deleted by user request]",
                gif_url="",
            )

        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        user.username = f"deleted_{user.id}_{timestamp}"
        user.email = f"deleted_{user.id}_{timestamp}@invalid.local"
        user.bio = ""
        user.website_url = ""
        user.social_x = ""
        user.social_discord = ""
        user.is_active = False
        user.set_unusable_password()
        user.save()
        logout(self.request)
        messages.success(self.request, "Account deletion workflow completed.")
        return super().form_valid(form)
