from django.conf import settings
from django.db import models


class SiteBranding(models.Model):
    THEME_PRESETS = (
        ("default", "Default"),
        ("dekcx", "dekcx"),
    )

    site_name = models.CharField(max_length=120, default="dChat")
    theme_preset = models.CharField(max_length=32, choices=THEME_PRESETS, default="default")
    logo_url = models.URLField(blank=True)
    accent_hex = models.CharField(max_length=7, default=settings.DEFAULT_ACCENT_HEX)
    bg_hex = models.CharField(max_length=7, default=settings.DEFAULT_BG_HEX)
    surface_hex = models.CharField(max_length=7, default=settings.DEFAULT_SURFACE_HEX)
    text_hex = models.CharField(max_length=7, default=settings.DEFAULT_TEXT_HEX)
    muted_text_hex = models.CharField(max_length=7, default=settings.DEFAULT_MUTED_TEXT_HEX)
    link_hex = models.CharField(max_length=7, default=settings.DEFAULT_LINK_HEX)
    border_radius_px = models.PositiveSmallIntegerField(default=10)
    klipy_app_key = models.CharField(max_length=255, blank=True, default="")
    klipy_content_filter = models.CharField(max_length=16, default=settings.KLIPY_CONTENT_FILTER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.site_name


class FooterLink(models.Model):
    label = models.CharField(max_length=60)
    url = models.URLField()
    sort_order = models.PositiveSmallIntegerField(default=0)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return self.label


class SetupState(models.Model):
    completed_at = models.DateTimeField(auto_now_add=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    def __str__(self) -> str:
        return f"Setup completed at {self.completed_at.isoformat()}"


class LegalDocument(models.Model):
    DOC_TYPES = (
        ("terms", "Terms of Service"),
        ("privacy", "Privacy Policy"),
        ("cookies", "Cookie Policy"),
    )
    doc_type = models.CharField(max_length=20, choices=DOC_TYPES, unique=True)
    version = models.CharField(max_length=20, default="v1")
    title = models.CharField(max_length=120)
    body_markdown = models.TextField()
    published_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["doc_type"]

    def __str__(self) -> str:
        return f"{self.get_doc_type_display()} ({self.version})"


class UserLegalConsent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    terms_version = models.CharField(max_length=20, blank=True)
    privacy_version = models.CharField(max_length=20, blank=True)
    cookies_version = models.CharField(max_length=20, blank=True)
    accepted_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "terms_version", "privacy_version", "cookies_version")

    def __str__(self) -> str:
        return f"{self.user} legal consent at {self.accepted_at.isoformat()}"


class ChangeLogEntry(models.Model):
    version = models.CharField(max_length=20, unique=True, blank=True)
    title = models.CharField(max_length=180)
    body_markdown = models.TextField()
    released_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-released_at"]

    def save(self, *args, **kwargs):
        if not self.version:
            latest = ChangeLogEntry.objects.order_by("-released_at").first()
            if not latest:
                self.version = "0.1"
            else:
                try:
                    self.version = f"{float(latest.version) + 0.1:.1f}"
                except Exception:
                    self.version = "0.1"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"v{self.version} - {self.title}"
