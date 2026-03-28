from django.urls import path

from apps.forum.chat_views import chatroom_root, chatroom_send, chatroom_updates, chatroom_view, user_chat_messages
from apps.forum.views import (
    HomeView,
    ModerationQueueView,
    ThreadDetailView,
    edit_post,
    grant_reputation,
    hard_delete_thread,
    moderate_report,
    post_reply,
    report_content,
    restore_target,
    set_thread_flag,
    soft_delete_target,
    thread_create,
    thread_events,
    thread_legacy_redirect,
    thread_posts_partial,
    vote,
    warn_user,
)

app_name = "forum"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("chat/", chatroom_root, name="chatroom_root"),
    path("chat/<slug:category_slug>/", chatroom_view, name="chatroom"),
    path("chat/<slug:category_slug>/send/", chatroom_send, name="chatroom_send"),
    path("chat/<slug:category_slug>/updates/", chatroom_updates, name="chatroom_updates"),
    path("chat/users/<slug:username>/", user_chat_messages, name="user_chat_messages"),
    path("threads/new/", thread_create, name="thread_create"),
    path("thread/<slug:category_slug>/<slug:thread_slug>-<int:thread_id>/", ThreadDetailView.as_view(), name="thread_detail"),
    path("threads/<int:thread_id>/", thread_legacy_redirect, name="thread_detail_legacy"),
    path("threads/<int:thread_id>/reply/", post_reply, name="post_reply"),
    path("threads/<int:thread_id>/posts-fragment/", thread_posts_partial, name="thread_posts_partial"),
    path("threads/<int:thread_id>/events/", thread_events, name="thread_events"),
    path("posts/<int:post_id>/edit/", edit_post, name="post_edit"),
    path("vote/", vote, name="vote"),
    path("reputation/grant/", grant_reputation, name="grant_reputation"),
    path("report/", report_content, name="report"),
    path("moderation/", ModerationQueueView.as_view(), name="moderation_queue"),
    path("moderation/reports/<int:report_id>/", moderate_report, name="moderate_report"),
    path("moderation/warn/", warn_user, name="warn_user"),
    path("moderation/soft-delete/", soft_delete_target, name="soft_delete"),
    path("moderation/restore/", restore_target, name="restore"),
    path("threads/<int:thread_id>/nuke/", hard_delete_thread, name="hard_delete_thread"),
    path("threads/<int:thread_id>/flags/", set_thread_flag, name="thread_flags"),
]
