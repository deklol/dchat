from urllib.parse import urlparse

from django import forms
from django.conf import settings
from django.utils.text import slugify

from apps.core.uploads import validate_uploaded_image
from apps.forum.models import ChatMessage, Post, Tag, Thread


def is_allowed_klipy_host(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    return hostname == "klipy.com" or hostname.endswith(".klipy.com")


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    widget = MultipleImageInput

    def clean(self, data, initial=None):
        if not data:
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        return list(data)


class ThreadForm(forms.ModelForm):
    tags_csv = forms.CharField(required=False, help_text="Comma-separated tags.")
    attachment = forms.FileField(required=False)

    class Meta:
        model = Thread
        fields = ("category", "title", "body_markdown")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].widget.attrs.update({"placeholder": "Thread title..."})
        self.fields["body_markdown"].required = False
        self.fields["body_markdown"].widget.attrs.update(
            {
                "placeholder": "Write the opening post or attach an image thread. Markdown, @mentions, and embeds work here...",
                "rows": 12,
                "data-markdown-input": "true",
            }
        )
        self.fields["tags_csv"].widget.attrs.update({"placeholder": "retro, announcements, help...", "spellcheck": "false"})
        self.fields["attachment"].widget.attrs.update({"accept": ".png,.jpg,.jpeg,.gif"})

    def clean(self):
        cleaned_data = super().clean()
        body = (cleaned_data.get("body_markdown") or "").strip()
        attachment = cleaned_data.get("attachment")
        if not body and not attachment:
            raise forms.ValidationError("Add thread text or upload an image.")
        cleaned_data["body_markdown"] = body
        return cleaned_data

    def clean_attachment(self):
        file = self.cleaned_data.get("attachment")
        if not file:
            return file
        return validate_uploaded_image(file, max_bytes=settings.MAX_UPLOAD_BYTES, max_mb=settings.MAX_UPLOAD_MB)

    def save(self, commit=True):
        thread = super().save(commit=commit)
        tags_raw = self.cleaned_data.get("tags_csv", "")
        tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        tag_objs = []
        for name in tags[:8]:
            tag, _ = Tag.objects.get_or_create(name=name, defaults={"slug": slugify(name)})
            tag_objs.append(tag)
        if commit:
            thread.tags.set(tag_objs)
        else:
            self._pending_tags = tag_objs
        return thread


class PostForm(forms.ModelForm):
    attachment = forms.FileField(required=False)

    class Meta:
        model = Post
        fields = ("body_markdown",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["body_markdown"].widget.attrs.update(
            {
                "placeholder": "Write a reply. Markdown, @mentions, and embeds work here...",
                "rows": 10,
                "data-markdown-input": "true",
            }
        )
        self.fields["attachment"].widget.attrs.update({"accept": ".png,.jpg,.jpeg,.gif"})

    def clean_attachment(self):
        file = self.cleaned_data.get("attachment")
        if not file:
            return file
        return validate_uploaded_image(file, max_bytes=settings.MAX_UPLOAD_BYTES, max_mb=settings.MAX_UPLOAD_MB)


class ChatMessageForm(forms.ModelForm):
    attachments = MultipleImageField(
        required=False,
        widget=MultipleImageInput(
            attrs={
                "accept": ".png,.jpg,.jpeg,.gif",
                "multiple": True,
            }
        ),
    )

    class Meta:
        model = ChatMessage
        fields = ("body_markdown", "gif_url")
        widgets = {
            "gif_url": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["body_markdown"].required = False
        self.fields["body_markdown"].label = "Message"
        self.fields["body_markdown"].widget.attrs.update(
            {
                "placeholder": "Message the room. Markdown, @mentions, quotes, images, and embeds work here...",
                "rows": 5,
                "data-markdown-input": "true",
            }
        )

    def clean_gif_url(self):
        value = (self.cleaned_data.get("gif_url") or "").strip()
        if not value:
            return ""
        if not is_allowed_klipy_host(value):
            raise forms.ValidationError("Invalid GIF selection.")
        return value

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        for file in files:
            validate_uploaded_image(file, max_bytes=settings.MAX_UPLOAD_BYTES, max_mb=settings.MAX_UPLOAD_MB)
        return files

    def clean(self):
        cleaned_data = super().clean()
        body = (cleaned_data.get("body_markdown") or "").strip()
        attachments = cleaned_data.get("attachments") or []
        gif_url = cleaned_data.get("gif_url") or ""
        if not body and not attachments and not gif_url:
            raise forms.ValidationError("Message cannot be empty.")
        cleaned_data["body_markdown"] = body
        return cleaned_data
