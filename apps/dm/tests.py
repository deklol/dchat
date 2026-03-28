from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.dm.models import DirectConversation, DirectMessage, DirectMessageAttachment

User = get_user_model()


def tiny_png_upload(name: str = "photo.png") -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class DirectMessageTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", email="alice@example.com", password="Password123!")
        self.bob = User.objects.create_user(username="bob", email="bob@example.com", password="Password123!")
        self.client.login(username="alice", password="Password123!")

    def test_start_dm_and_send(self):
        resp = self.client.post(
            reverse("dm:start"),
            data={"username": "bob", "body": "hello bob"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        convo = DirectConversation.for_users(self.alice, self.bob)
        self.assertTrue(DirectMessage.objects.filter(conversation=convo, sender=self.alice, recipient=self.bob).exists())

    def test_quick_dm_send(self):
        resp = self.client.post(
            reverse("dm:quick_send", kwargs={"username": "bob"}),
            data={"body": "quick ping"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            DirectMessage.objects.filter(conversation__user_low=self.alice, conversation__user_high=self.bob).exists()
        )

    def test_start_dm_allows_attachment_only(self):
        image = tiny_png_upload()

        resp = self.client.post(
            reverse("dm:start"),
            data={"username": "bob", "body": "", "attachments": [image]},
            follow=True,
        )

        self.assertEqual(resp.status_code, 200)
        message = DirectMessage.objects.get(conversation__user_low=self.alice, conversation__user_high=self.bob)
        self.assertEqual(message.get_body(), "")
        self.assertTrue(DirectMessageAttachment.objects.filter(message=message, original_name="photo.png").exists())
