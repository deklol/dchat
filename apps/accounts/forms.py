from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.core.uploads import validate_uploaded_image
from apps.accounts.utils import captcha_failure_message, get_math_captcha_question, verify_math_captcha

User = get_user_model()


class CaptchaAwareAuthenticationForm(AuthenticationForm):
    captcha_answer = forms.IntegerField()

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, request=request, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "spellcheck": "false", "placeholder": "Username..."}
        )
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password", "placeholder": "Password..."})
        if self.request and settings.CAPTCHA_ENABLED:
            question = get_math_captcha_question(self.request.session, "login")
            self.fields["captcha_answer"].label = question
            self.fields["captcha_answer"].widget.attrs.update({"inputmode": "numeric", "placeholder": "Answer..."})
        else:
            self.fields["captcha_answer"].required = False
            self.fields["captcha_answer"].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        if self.request and settings.CAPTCHA_ENABLED:
            answer = cleaned.get("captcha_answer")
            if not verify_math_captcha(self.request.session, "login", str(answer)):
                raise forms.ValidationError(captcha_failure_message())
        return cleaned


class SignUpForm(UserCreationForm):
    email = forms.EmailField()
    captcha_answer = forms.IntegerField()
    accept_terms = forms.BooleanField(required=True)
    accept_privacy = forms.BooleanField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2", "accept_terms", "accept_privacy")

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "spellcheck": "false", "placeholder": "Username..."}
        )
        self.fields["email"].widget.attrs.update({"autocomplete": "email", "placeholder": "Email...", "spellcheck": "false"})
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password", "placeholder": "Password..."})
        self.fields["password2"].widget.attrs.update(
            {"autocomplete": "new-password", "placeholder": "Confirm password..."}
        )
        if self.request and settings.CAPTCHA_ENABLED:
            question = get_math_captcha_question(self.request.session, "register")
            self.fields["captcha_answer"].label = question
            self.fields["captcha_answer"].widget.attrs.update({"inputmode": "numeric", "placeholder": "Answer..."})
        else:
            self.fields["captcha_answer"].required = False
            self.fields["captcha_answer"].widget = forms.HiddenInput()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Email already in use.")
        return email

    def clean(self):
        cleaned = super().clean()
        if self.request and settings.CAPTCHA_ENABLED:
            answer = cleaned.get("captcha_answer")
            if not verify_math_captcha(self.request.session, "register", str(answer)):
                raise forms.ValidationError(captcha_failure_message())
        return cleaned


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("avatar", "bio", "website_url", "social_x", "social_discord", "email_digest_enabled")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bio"].widget.attrs.update({"placeholder": "Tell people a bit about yourself..."})
        self.fields["website_url"].widget.attrs.update({"placeholder": "https://example.com", "autocomplete": "url"})
        self.fields["social_x"].widget.attrs.update({"placeholder": "https://x.com/yourname", "autocomplete": "url"})
        self.fields["social_discord"].widget.attrs.update({"placeholder": "username#0000", "spellcheck": "false"})

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar
        return validate_uploaded_image(avatar, max_bytes=settings.MAX_UPLOAD_BYTES, max_mb=settings.MAX_UPLOAD_MB)


class DeleteAccountForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_text = forms.CharField(help_text="Type DELETE to confirm.")
    delete_content = forms.BooleanField(
        required=False,
        help_text="When checked, your thread/reply bodies are soft-deleted and anonymized.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password", "placeholder": "Password..."})
        self.fields["confirm_text"].widget.attrs.update({"placeholder": "DELETE", "spellcheck": "false"})
