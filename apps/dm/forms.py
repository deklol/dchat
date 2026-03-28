from django import forms
from django.conf import settings

from apps.core.uploads import validate_uploaded_image


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


class DirectMessageForm(forms.Form):
    body = forms.CharField(
        max_length=4000,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Write a direct message...",
            }
        ),
    )
    attachments = MultipleImageField(
        required=False,
        widget=MultipleImageInput(
            attrs={
                "accept": ".png,.jpg,.jpeg,.gif",
                "multiple": True,
            }
        ),
    )

    def clean_body(self) -> str:
        body = (self.cleaned_data.get("body") or "").strip()
        return body

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        for file in files:
            validate_uploaded_image(file, max_bytes=settings.MAX_UPLOAD_BYTES, max_mb=settings.MAX_UPLOAD_MB)
        return files

    def clean(self):
        cleaned_data = super().clean()
        body = (cleaned_data.get("body") or "").strip()
        attachments = cleaned_data.get("attachments") or []
        if not body and not attachments:
            raise forms.ValidationError("Message cannot be empty.")
        cleaned_data["body"] = body
        return cleaned_data


class QuickDirectMessageForm(forms.Form):
    body = forms.CharField(
        max_length=1000,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
            }
        ),
    )

    def clean_body(self) -> str:
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Message cannot be empty.")
        return body


class StartDirectMessageForm(forms.Form):
    username = forms.CharField(max_length=150)
    body = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
            }
        ),
    )
    attachments = MultipleImageField(
        required=False,
        widget=MultipleImageInput(
            attrs={
                "accept": ".png,.jpg,.jpeg,.gif",
                "multiple": True,
            }
        ),
    )

    def clean_username(self) -> str:
        username = (self.cleaned_data.get("username") or "").strip().lstrip("@")
        if not username:
            raise forms.ValidationError("Username is required.")
        return username

    def clean_body(self) -> str:
        body = (self.cleaned_data.get("body") or "").strip()
        return body

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        for file in files:
            validate_uploaded_image(file, max_bytes=settings.MAX_UPLOAD_BYTES, max_mb=settings.MAX_UPLOAD_MB)
        return files

    def clean(self):
        cleaned_data = super().clean()
        body = (cleaned_data.get("body") or "").strip()
        attachments = cleaned_data.get("attachments") or []
        if not body and not attachments:
            raise forms.ValidationError("Message cannot be empty.")
        cleaned_data["body"] = body
        return cleaned_data


class DirectMessagePreferenceForm(forms.Form):
    allow_incoming = forms.BooleanField(
        required=False,
        label="Allow incoming DMs from other users",
    )


class ReportDirectMessageForm(forms.Form):
    reason = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Optional report reason...",
            }
        ),
    )
