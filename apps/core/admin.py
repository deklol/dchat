from django.contrib import admin
from django import forms

from .models import ChangeLogEntry, FooterLink, LegalDocument, SetupState, SiteBranding, UserLegalConsent

THEME_PALETTES = {
    "default": {
        "accent_hex": "#f39c12",
        "bg_hex": "#0f1217",
        "surface_hex": "#1a1f29",
        "text_hex": "#e5e7eb",
        "muted_text_hex": "#9ca3af",
        "link_hex": "#7cc4ff",
        "border_radius_px": 10,
    },
    "dekcx": {
        "accent_hex": "#FF9900",
        "bg_hex": "#06060f",
        "surface_hex": "#111827",
        "text_hex": "#e8eaf0",
        "muted_text_hex": "#8899aa",
        "link_hex": "#4A8FCC",
        "border_radius_px": 0,
    },
}


class SiteBrandingAdminForm(forms.ModelForm):
    apply_preset_palette = forms.BooleanField(
        required=False,
        initial=False,
        help_text="Apply the selected preset's default colors now. You can still customize colors after.",
        label="Apply Preset Palette",
    )

    class Meta:
        model = SiteBranding
        fields = "__all__"

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("apply_preset_palette"):
            palette = THEME_PALETTES.get(instance.theme_preset, {})
            for field, value in palette.items():
                setattr(instance, field, value)
        if commit:
            instance.save()
        return instance


@admin.register(SiteBranding)
class SiteBrandingAdmin(admin.ModelAdmin):
    form = SiteBrandingAdminForm
    list_display = ("site_name", "theme_preset", "accent_hex", "updated_at")
    fieldsets = (
        ("Brand", {"fields": ("site_name", "logo_url")}),
        ("Theme", {"fields": ("theme_preset", "apply_preset_palette")}),
        (
            "Colors",
            {
                "description": "These color tokens remain editable even when a theme preset is active.",
                "fields": (
                    "accent_hex",
                    "bg_hex",
                    "surface_hex",
                    "text_hex",
                    "muted_text_hex",
                    "link_hex",
                    "border_radius_px",
                ),
            },
        ),
        (
            "Chat Integrations",
            {
                "description": "Optional client-side GIF search. Leave the key blank to keep KLIPY disabled.",
                "fields": ("klipy_app_key", "klipy_content_filter"),
            },
        ),
    )


@admin.register(FooterLink)
class FooterLinkAdmin(admin.ModelAdmin):
    list_display = ("label", "url", "sort_order", "enabled")
    list_editable = ("sort_order", "enabled")


@admin.register(SetupState)
class SetupStateAdmin(admin.ModelAdmin):
    list_display = ("completed_at", "completed_by")


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ("doc_type", "version", "published_at")


@admin.register(UserLegalConsent)
class UserLegalConsentAdmin(admin.ModelAdmin):
    list_display = ("user", "terms_version", "privacy_version", "cookies_version", "accepted_at")


@admin.register(ChangeLogEntry)
class ChangeLogEntryAdmin(admin.ModelAdmin):
    list_display = ("version", "title", "released_at")
