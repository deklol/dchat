from decimal import Decimal

from django.db.models import Count, Sum

from apps.forum.models import ChatMessage, ModerationWarning, Post, ReputationGrant, Thread


def build_user_forum_stats(user_ids: list[int]) -> dict[int, dict[str, Decimal | int]]:
    ids = sorted({user_id for user_id in user_ids if user_id})
    if not ids:
        return {}

    thread_counts = {
        row["author_id"]: row["total"]
        for row in Thread.objects.filter(author_id__in=ids, is_deleted=False)
        .values("author_id")
        .annotate(total=Count("id"))
    }
    reply_counts = {
        row["author_id"]: row["total"]
        for row in Post.objects.filter(author_id__in=ids, is_deleted=False)
        .values("author_id")
        .annotate(total=Count("id"))
    }
    chat_counts = {
        row["author_id"]: row["total"]
        for row in ChatMessage.objects.filter(author_id__in=ids, is_deleted=False)
        .values("author_id")
        .annotate(total=Count("id"))
    }
    grant_totals = {
        row["recipient_id"]: row["total"] or 0
        for row in ReputationGrant.objects.filter(recipient_id__in=ids)
        .values("recipient_id")
        .annotate(total=Count("id"))
    }
    warning_totals = {
        row["user_id"]: row["total"] or 0
        for row in ModerationWarning.objects.filter(user_id__in=ids)
        .values("user_id")
        .annotate(total=Sum("rep_penalty"))
    }

    return {
        user_id: {
            "topics": thread_counts.get(user_id, 0),
            "replies": reply_counts.get(user_id, 0),
            "chat_messages": chat_counts.get(user_id, 0),
            "posts": thread_counts.get(user_id, 0) + reply_counts.get(user_id, 0) + chat_counts.get(user_id, 0),
            "rep": Decimal(grant_totals.get(user_id, 0) - warning_totals.get(user_id, 0))
            + (Decimal(chat_counts.get(user_id, 0)) / Decimal("10")),
        }
        for user_id in ids
    }


def apply_user_forum_stats(user, stats_by_user_id: dict[int, dict[str, int]]) -> None:
    stats = stats_by_user_id.get(getattr(user, "id", None), {})
    user.forum_topic_count = stats.get("topics", 0)
    user.forum_reply_count = stats.get("replies", 0)
    user.forum_chat_message_count = stats.get("chat_messages", 0)
    user.forum_post_count = stats.get("posts", 0)
    user.forum_rep = stats.get("rep", Decimal("0"))


def granted_post_reputation_ids(user, post_ids: list[int]) -> set[int]:
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(
        ReputationGrant.objects.filter(actor=user, post_id__in=post_ids).values_list("post_id", flat=True)
    )


def granted_thread_reputation_ids(user, thread_ids: list[int]) -> set[int]:
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(
        ReputationGrant.objects.filter(actor=user, thread_id__in=thread_ids).values_list("thread_id", flat=True)
    )
