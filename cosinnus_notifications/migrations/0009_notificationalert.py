# Generated by Django 2.1.10 on 2020-01-27 16:48

from django.conf import settings
import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        migrations.swappable_dependency(settings.COSINNUS_GROUP_OBJECT_MODEL),
        ('cosinnus', '0051_auto_20191017_2138'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('cosinnus_notifications', '0008_auto_20190513_1521'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationAlert',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_id', models.CharField(max_length=100, verbose_name='Notification ID')),
                ('reason_key', models.CharField(blank=True, help_text='One of `cosinnus_notifications.alerts.ALERT_REASONS` or None.', max_length=32, null=True, verbose_name='Alert Reason key')),
                ('object_id', models.PositiveIntegerField()),
                ('last_event_at', models.DateTimeField(auto_now_add=True)),
                ('seen', models.BooleanField(default=False, help_text='Whether the owner has seen this alert. May reset to unseen on new events of multi or bundle alerts.')),
                ('type', models.PositiveSmallIntegerField(choices=[(0, 'Single Alert'), (1, 'Multi User Alert'), (2, 'Bundled Alert')], default=0, editable=False, help_text='The type of the Alert. Can only morph from single to multi or from single to bundle!', verbose_name='Alert State')),
                ('target_title', models.CharField(help_text='Cached version of the title of the target object', max_length=250)),
                ('target_url', models.URLField(blank=True, help_text='Target URL the alert points to, usually a cached version of the URL of the target object', max_length=250, null=True)),
                ('label', models.TextField(help_text='An untranslated, unwrapped i18n text, to be retranslated at retrieval time')),
                ('icon_or_image_url', models.CharField(blank=True, help_text='Either a URL to an image thumbnail, or a fa-icon string. Distinguished by frontend at display time', max_length=250, null=True)),
                ('subtitle', models.CharField(blank=True, help_text='Usually a cached version of the group name, or None', max_length=250, null=True)),
                ('subtitle_icon', models.CharField(blank=True, help_text='fa-icon string or None', max_length=250, null=True)),
                ('item_hash', models.CharField(help_text='A unique-per-user pseudo-hash to identify an alert and detect multi-user alerts.Consists of `[portal-id]/[group-id]/[item-model]/[notification-id]/[item-id]`', max_length=250)),
                ('bundle_hash', models.CharField(help_text='A non-unique hash used to detect very similar events to merge as a bundle.Consists of `[portal-id]/[group-id]/[item-model]/[notification-id]/[action-user-id]`', max_length=250)),
                ('counter', models.PositiveIntegerField(default=0, help_text='A counter for displaying a number in the alert like "Amy and [counter] more liked your post".Used in multi and bundle alerts.')),
                ('multi_user_list', django.contrib.postgres.fields.jsonb.JSONField(blank=True, help_text='Only filled if type==TYPE_MULTI_USER_ALERT, None else.Contains a list of objects for referenced users [{"user_id", "title" (username), "url", "icon_or_image_url"}, ...]', null=True)),
                ('bundle_list', django.contrib.postgres.fields.jsonb.JSONField(blank=True, help_text='Only filled if type==TYPE_BUNDLE_ALERT, None else.Contains a list of objects for referenced content objects [{"object_id", "title", "url", "icon_or_image_url"}, ...]', null=True)),
                ('action_user', models.ForeignKey(help_text='For multi-user alerts, this points to the last user who changed anything about this alert.', on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Last user who caused this notification event')),
                ('content_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.ContentType')),
                ('group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='notifcation_alerts', to=settings.COSINNUS_GROUP_OBJECT_MODEL)),
                ('portal', models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, related_name='notification_alerts', to='cosinnus.CosinnusPortal', verbose_name='Portal')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Owner of the alert')),
            ],
            options={
                'ordering': ('last_event_at',),
            },
        ),
    ]
