from django import forms
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model

from apps.core.legal_defaults import legal_document_defaults
from apps.core.models import ChangeLogEntry, LegalDocument, SiteBranding

User = get_user_model()


class FirstRunSetupForm(forms.Form):
    KLIPY_CONTENT_FILTER_CHOICES = (
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    )

    site_name = forms.CharField(max_length=120)
    theme_preset = forms.ChoiceField(choices=SiteBranding.THEME_PRESETS, initial="default")
    accent_hex = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    bg_hex = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    surface_hex = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    text_hex = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    muted_text_hex = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    link_hex = forms.RegexField(regex=r"^#[0-9A-Fa-f]{6}$", max_length=7)
    admin_username = forms.CharField(max_length=30)
    admin_email = forms.EmailField(
        help_text="The first account becomes user id 1. This email is shown publicly on the legal pages by default."
    )
    admin_password = forms.CharField(widget=forms.PasswordInput())
    klipy_app_key = forms.CharField(
        max_length=255,
        required=False,
        help_text="Optional. Get a KLIPY key from partner.klipy.com if you want GIF search enabled at launch.",
    )
    klipy_content_filter = forms.ChoiceField(choices=KLIPY_CONTENT_FILTER_CHOICES, initial="medium", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site_name"].widget.attrs.update({"placeholder": "dChat"})
        self.fields["accent_hex"].widget.attrs.update({"placeholder": "#f39c12", "spellcheck": "false"})
        self.fields["bg_hex"].widget.attrs.update({"placeholder": "#0f1217", "spellcheck": "false"})
        self.fields["surface_hex"].widget.attrs.update({"placeholder": "#1a1f29", "spellcheck": "false"})
        self.fields["text_hex"].widget.attrs.update({"placeholder": "#e5e7eb", "spellcheck": "false"})
        self.fields["muted_text_hex"].widget.attrs.update({"placeholder": "#9ca3af", "spellcheck": "false"})
        self.fields["link_hex"].widget.attrs.update({"placeholder": "#7cc4ff", "spellcheck": "false"})
        self.fields["admin_username"].widget.attrs.update(
            {"autocomplete": "username", "spellcheck": "false", "placeholder": "Admin username..."}
        )
        self.fields["admin_email"].widget.attrs.update(
            {"autocomplete": "email", "placeholder": "Public legal contact email..."}
        )
        self.fields["admin_password"].widget.attrs.update(
            {"autocomplete": "new-password", "placeholder": "Admin password..."}
        )
        self.fields["klipy_app_key"].widget.attrs.update(
            {"spellcheck": "false", "placeholder": "Optional KLIPY API key..."}
        )

    def save(self):
        user = User.objects.create_superuser(
            username=self.cleaned_data["admin_username"],
            email=self.cleaned_data["admin_email"],
            password=self.cleaned_data["admin_password"],
        )
        SiteBranding.objects.update_or_create(
            id=1,
            defaults={
                "site_name": self.cleaned_data["site_name"],
                "theme_preset": self.cleaned_data["theme_preset"],
                "accent_hex": self.cleaned_data["accent_hex"],
                "bg_hex": self.cleaned_data["bg_hex"],
                "surface_hex": self.cleaned_data["surface_hex"],
                "text_hex": self.cleaned_data["text_hex"],
                "muted_text_hex": self.cleaned_data["muted_text_hex"],
                "link_hex": self.cleaned_data["link_hex"],
                "klipy_app_key": self.cleaned_data["klipy_app_key"].strip(),
                "klipy_content_filter": self.cleaned_data["klipy_content_filter"] or "medium",
            },
        )
        defaults = legal_document_defaults(self.cleaned_data["site_name"], self.cleaned_data["admin_email"])
        for doc_type, payload in defaults.items():
            LegalDocument.objects.get_or_create(
                doc_type=doc_type,
                defaults=payload,
            )
        if not ChangeLogEntry.objects.exists():
            ChangeLogEntry.objects.bulk_create(
                [
                    ChangeLogEntry(
                        version="0.1",
                        title="Initial release scaffold",
                        body_markdown="- Base forum platform scaffolded\n- Setup wizard enabled\n- Core security defaults added",
                    ),
                    ChangeLogEntry(
                        version="0.2",
                        title="Production hardening and moderation rollout",
                        body_markdown=(
                            "- SSE realtime updates\n"
                            "- GDPR export/delete workflows\n"
                            "- Reports, moderation queue, soft delete/restore, and logs\n"
                            "- External link warning gateway and security headers\n"
                            "- Backup/restore and health/metrics endpoints"
                        ),
                    ),
                    ChangeLogEntry(
                        version="0.3",
                        title="dekcx theme preset added",
                        body_markdown=(
                            "- Optional `dekcx` theme preset inspired by a Habbo archive visual language\n"
                            "- Theme preset selector in Site Branding admin\n"
                            "- Preset palette apply button while preserving custom color control"
                        ),
                    ),
                    ChangeLogEntry(
                        version="0.4",
                        title="Discord + Zulip inspired UI redesign",
                        body_markdown=(
                            "- Reworked default visual shell around Discord-style layout primitives\n"
                            "- Added denser channel/thread presentation inspired by Zulip navigation clarity\n"
                            "- Refined thread/reply surfaces and user popup cards for production polish"
                        ),
                    ),
                    ChangeLogEntry(
                        version="0.5",
                        title="Forum UI recovery pass",
                        body_markdown=(
                            "- Rebuilt the default interface around a Discord-like workspace with denser topic scanning\n"
                            "- Added thread inspectors, functional stream filters, and redesigned auth/profile/moderation screens\n"
                            "- Replaced the footer with a sticky forum-style information block that fits the main theme"
                        ),
                    ),
                    ChangeLogEntry(
                        version="0.6",
                        title="Threaded reply and mention pass",
                        body_markdown=(
                            "- Rebuilt thread detail replies into nested forum posts\n"
                            "- Added working Markdown composer tools and visible reply submission flow\n"
                            "- Added @mention autocomplete and inbox notifications that link back to the relevant thread or reply\n"
                            "- Removed duplicate thread search from the home pane and trimmed footer utility links"
                        ),
                    ),
                    ChangeLogEntry(
                        version="0.7",
                        title="Visual refinement and cache-busting",
                        body_markdown=(
                            "- Fixed clipped thread/reply corner rendering and simplified the desktop workspace chrome\n"
                            "- Reworked the `dekcx` preset into a palette-first theme for the modern layout\n"
                            "- Added static asset cache-busting tied to the app version"
                        ),
                    ),
                    ChangeLogEntry(
                        version="0.8",
                        title="Forum footer and author stats pass",
                        body_markdown=(
                            "- Moved the footer into the content flow and trimmed persistent footer behavior\n"
                            "- Added forum stats to thread starters and replies\n"
                            "- Unified profile popup behavior across footer and forum links"
                        ),
                    ),
                    ChangeLogEntry(
                        version="0.9",
                        title="Sidebar information redesign",
                        body_markdown=(
                            "- Removed the old footer and moved app/community/legal info into reusable sidebar modules\n"
                            "- Added shared version, changelog, FAQ, and community sidebar blocks\n"
                            "- Removed background footer polling logic"
                        ),
                    ),
                    ChangeLogEntry(
                        version="1.0",
                        title="Direct messaging and mention depth pass",
                        body_markdown=(
                            "- Added deep-link post permalinks and thread-level unread mention indicators\n"
                            "- Added image-led threads and encrypted direct messages with reported-DM review flow\n"
                            "- Added DM actions and richer presence indicators in the user popup"
                        ),
                    ),
                    ChangeLogEntry(
                        version="1.1",
                        title="Reputation and user card expansion",
                        body_markdown=(
                            "- Replaced vote-derived rep with real `+Rep` grants and moderator warning penalties\n"
                            "- Added `+Rep` and `Warn` actions to thread starters and replies\n"
                            "- Expanded the user popup and profile page with forum stats plus recent topics and replies\n"
                            "- Fixed long subthread titles in the topics sidebar with a stable two-line layout"
                        ),
                    ),
                    ChangeLogEntry(
                        version="1.2",
                        title="Live inbox shell updates",
                        body_markdown=(
                            "- Added lightweight live inbox badge updates so new DMs and inbox notifications appear without a full page refresh\n"
                            "- Invalidated unread-count caches on DM send/read and notification read paths for consistent shell state\n"
                            "- Added an Inbox Settings shortcut on the owner profile page\n"
                            "- Linked the footer `dChat` brand text to the public GitHub repository\n"
                            "- Added per-conversation DM icons to the guild rail with a context menu action to hide chats from the rail\n"
                            "- Brought DMs closer to thread capability parity with markdown/link embeds and multiple image uploads"
                        ),
                    ),
                    ChangeLogEntry(
                        version="1.3",
                        title="Category chatrooms and publish polish",
                        body_markdown=(
                            "- Added category-based live chatrooms with the latest three related topics pinned in the room header\n"
                            "- Reworked chat message continuity so consecutive messages chain cleanly and only reset identity after a long gap\n"
                            "- Moved chat message actions into a compact far-right hover affordance that no longer adds spacing between messages\n"
                            "- Added Django admin KLIPY controls through Site Branding so GIF search can be enabled without editing env files\n"
                            "- Removed the redundant top-nav Chatroom link and tightened the public-facing release docs"
                        ),
                    ),
                ]
            )
        member_group, _ = Group.objects.get_or_create(name="Member")
        moderator_group, _ = Group.objects.get_or_create(name="Moderator")
        admin_group, _ = Group.objects.get_or_create(name="Admin")

        thread_add = Permission.objects.get(codename="add_thread")
        post_add = Permission.objects.get(codename="add_post")
        vote_add = Permission.objects.get(codename="add_vote")
        report_add = Permission.objects.get(codename="add_report")
        report_change = Permission.objects.get(codename="change_report")
        post_change = Permission.objects.get(codename="change_post")
        thread_change = Permission.objects.get(codename="change_thread")

        member_group.permissions.set([thread_add, post_add, vote_add, report_add])
        moderator_group.permissions.set(
            [thread_add, post_add, vote_add, report_add, report_change, post_change, thread_change]
        )
        admin_group.permissions.set(Permission.objects.all())
        user.groups.add(admin_group)
        return user
