from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.forum.chat_views import annotate_chat_messages
from apps.forum.models import Category, ChatMessage, ChatRoom, ModerationWarning, Post, Report, ReputationGrant, Thread, extract_mentions
from apps.forum.stats import build_user_forum_stats
from apps.forum.templatetags.forum_format import link_mentions

User = get_user_model()


class ForumFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", email="alice@example.com", password="Password123!")
        self.user.user_permissions.clear()
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.client.login(username="alice", password="Password123!")
        self.category = Category.objects.create(name="General", slug="general")

    def test_create_thread_and_reply(self):
        response = self.client.post(
            reverse("forum:thread_create"),
            data={"category": self.category.id, "title": "Hello", "body_markdown": "First post", "tags_csv": "intro"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        thread = Thread.objects.get(title="Hello")
        reply = self.client.post(
            reverse("forum:post_reply", kwargs={"thread_id": thread.id}),
            data={"body_markdown": "Reply body"},
            follow=True,
        )
        self.assertEqual(reply.status_code, 200)
        self.assertContains(reply, "Reply posted", status_code=200)

    def test_report_flow(self):
        thread = Thread.objects.create(category=self.category, author=self.user, title="Report me", body_markdown="x")
        response = self.client.post(
            reverse("forum:report"),
            data={"target_type": "thread", "target_id": thread.id, "reason": "spam"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Report.objects.filter(target_type="thread", target_id=thread.id).exists())

    def test_outbound_warning(self):
        response = self.client.get(reverse("outbound_link_warning") + "?u=https%3A%2F%2Fexample.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Leaving dChat")

    def test_mentions_create_notifications(self):
        thread = Thread.objects.create(category=self.category, author=self.user, title="Notify", body_markdown="start")
        bob = User.objects.create_user(username="bob", email="bob@example.com", password="Password123!")
        resp = self.client.post(
            reverse("forum:post_reply", kwargs={"thread_id": thread.id}),
            data={"body_markdown": "hi @bob"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(bob.notifications.filter(thread=thread, kind="mention").exists())

    def test_emails_do_not_create_mentions(self):
        self.assertEqual(extract_mentions("Questions: owner@example.com and hi @bob."), ["bob"])
        rendered = link_mentions("Email owner@example.com and ping @bob")
        self.assertIn("owner@example.com", rendered)
        self.assertIn('data-user-card="bob"', rendered)
        self.assertNotIn('data-user-card="dek"', rendered)

    def test_thread_url_uses_category_slug(self):
        archiving = Category.objects.create(name="Archiving", slug="Archiving")
        thread = Thread.objects.create(
            category=archiving,
            author=self.user,
            title="Archive mirror is now live",
            body_markdown="launch",
        )

        self.assertEqual(
            thread.get_absolute_url(),
            f"/thread/archiving/{thread.url_slug()}-{thread.id}/",
        )

    def test_old_topic_path_redirects_to_category_canonical(self):
        archiving = Category.objects.create(name="Archiving", slug="Archiving")
        thread = Thread.objects.create(
            category=archiving,
            author=self.user,
            title="Archive mirror is now live",
            body_markdown="launch",
        )

        response = self.client.get(f"/thread/topic/{thread.url_slug()}-{thread.id}/")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], thread.get_absolute_url())
        self.assertEqual(response["Location"], f"/thread/archiving/{thread.url_slug()}-{thread.id}/")

    def test_admin_can_nuke_thread(self):
        thread = Thread.objects.create(category=self.category, author=self.user, title="Nuke me", body_markdown="root")
        Post.objects.create(thread=thread, author=self.user, body_markdown="reply")

        detail = self.client.get(thread.get_absolute_url())
        self.assertContains(detail, "Nuke Thread")

        response = self.client.post(
            reverse("forum:hard_delete_thread", kwargs={"thread_id": thread.id}),
            data={"note": "cleanup"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Thread.objects.filter(id=thread.id).exists())
        self.assertFalse(Post.objects.filter(thread_id=thread.id).exists())

    def test_post_rep_can_only_be_given_once(self):
        bob = User.objects.create_user(username="bob", email="bob@example.com", password="Password123!")
        thread = Thread.objects.create(category=self.category, author=bob, title="Rep target", body_markdown="thread")
        post = Post.objects.create(thread=thread, author=bob, body_markdown="useful reply")

        first = self.client.post(
            reverse("forum:grant_reputation"),
            data={"target_type": "post", "target_id": post.id, "next": thread.get_absolute_url()},
            follow=True,
        )
        second = self.client.post(
            reverse("forum:grant_reputation"),
            data={"target_type": "post", "target_id": post.id, "next": thread.get_absolute_url()},
            follow=True,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ReputationGrant.objects.filter(actor=self.user, post=post).count(), 1)
        stats = build_user_forum_stats([bob.id])
        self.assertEqual(stats[bob.id]["rep"], 1)

    def test_warning_deducts_rep(self):
        bob = User.objects.create_user(username="bob2", email="bob2@example.com", password="Password123!")
        thread = Thread.objects.create(category=self.category, author=bob, title="Warn target", body_markdown="thread")
        post = Post.objects.create(thread=thread, author=bob, body_markdown="bad reply")
        ReputationGrant.objects.create(actor=self.user, recipient=bob, post=post)

        response = self.client.post(
            reverse("forum:warn_user"),
            data={"target_type": "post", "target_id": post.id, "note": "rule break", "next": thread.get_absolute_url()},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ModerationWarning.objects.filter(user=bob, post=post).exists())
        stats = build_user_forum_stats([bob.id])
        self.assertEqual(stats[bob.id]["rep"], 0)

    def test_chat_messages_only_reset_identity_after_twelve_hours(self):
        room = ChatRoom.for_category(self.category)
        first = ChatMessage.objects.create(room=room, author=self.user, body_markdown="first")
        second = ChatMessage.objects.create(room=room, author=self.user, body_markdown="second")
        third = ChatMessage.objects.create(room=room, author=self.user, body_markdown="third")

        base_time = timezone.now()
        ChatMessage.objects.filter(id=first.id).update(created_at=base_time)
        ChatMessage.objects.filter(id=second.id).update(created_at=base_time + timedelta(hours=1))
        ChatMessage.objects.filter(id=third.id).update(created_at=base_time + timedelta(hours=13, minutes=1))

        messages = list(ChatMessage.objects.filter(room=room).order_by("created_at"))
        annotate_chat_messages(messages, self.user)

        self.assertTrue(messages[0].show_identity)
        self.assertFalse(messages[1].show_identity)
        self.assertTrue(messages[2].show_identity)
