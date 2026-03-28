from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserPresence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("is_online", models.BooleanField(default=True)),
                (
                    "user",
                    models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="presence", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
    ]
