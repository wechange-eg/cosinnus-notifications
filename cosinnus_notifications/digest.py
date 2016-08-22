# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import timedelta
import logging

from django.template.loader import render_to_string
from django.utils import translation
from django.utils.safestring import mark_safe
from django.utils.timezone import now

from cosinnus.conf import settings
from cosinnus.models.group import CosinnusPortal
from cosinnus_notifications.models import UserNotificationPreference,\
    NotificationEvent
from cosinnus_notifications.notifications import NO_NOTIFICATIONS_ID,\
    ALL_NOTIFICATIONS_ID
from django.core.urlresolvers import reverse
from django.utils.html import strip_tags
from cosinnus.templatetags.cosinnus_tags import full_name, cosinnus_setting
from cosinnus.core.mail import send_mail_or_fail
from django.contrib.auth import get_user_model
from cosinnus.utils.permissions import check_object_read_access

logger = logging.getLogger('cosinnus')



def send_digest_for_current_portal(digest_setting):
    """ Sends out a daily/weekly digest email to all users *IN THE CURRENT PORTAL*
             who have any notification preferences set to that frequency.
        We will send all events that happened within this
        
        Will not use an own thread because it is assumend that this is run from a management command.
        TODO: We may want to split up the user-loop into 4 independent threads covering 1/4th of the users each
              to balance loads better.
    
        @param digest_setting: UserNotificationPreference.SETTING_DAILY or UserNotificationPreference.SETTING_WEEKLY
    """
    portal = CosinnusPortal.get_current()
    portal_group_ids = portal.groups.all().filter(is_active=True).values_list('id', flat=True)
    
    # TODO: get this from a (CosinusPortal?) DB field
    TIME_DIGEST_START = None
    if not TIME_DIGEST_START:
        TIME_DIGEST_START = now() - timedelta(days=UserNotificationPreference.SETTINGS_DAYS_DURATIONS[digest_setting])
    # TODO: save this to the DB now or after the digest finished
    TIME_DIGEST_END = now()
    
    # the main Notification Events QS. anything not in here did not happen in the digest's time span
    timescope_notification_events = NotificationEvent.objects.filter(date__gte=TIME_DIGEST_START, date__lt=TIME_DIGEST_END)
    
    users = get_user_model().objects.all().filter(id__in=portal.members)
    emailed = 0
    for user in users:
        # only active users that have logged in before accepted the TOS get notifications
        if not user.is_active or not user.last_login or not cosinnus_setting(user, 'tos_accepted'):
            continue
        
        # find out any notification preferences the user has for groups in this portal with the daily/weekly setting
        # if he doesn't have any, we will not send a mail for them
        prefs = UserNotificationPreference.objects.filter(user=user, group_id__in=portal_group_ids, setting=digest_setting)
        prefs = prefs.exclude(notification_id=NO_NOTIFICATIONS_ID)
        
        if len(prefs) == 0:
            continue
        
        # only for these groups does the user get any digest news at all
        pref_group_ids = list(set([pref.group for pref in prefs]))
        # get all notification events for these groups
        events = timescope_notification_events.filter(group_id__in=pref_group_ids)
        # and also only those where the user is in the intended audience
        events = events.filter(audience__contains=',%d,' % user.id)
        
        if events.count() == 0:
            continue
        
        # collect a comparable hash for all wanted user prefs
        wanted_group_notifications = ['%(group_id)d__%(notification_id)s' % {
            'group_id': pref.group_id,
            'notification_id': pref.notification_id,
        } for pref in prefs]
        
        # cluster event messages by group. from here on, the user will definitely get an email.
        body_html = ''
        for group in list(set(events.values_list('group', flat=True))): # FIXME: is values-list unique?
            group_events = events.filter(group=group).order_by('notification_id')
            
            
            # filter only those events that the user actually has in his prefs, for this group and also
            # check for target object existing, being visible to user, and other sanity checks if the user should see this object
            wanted_group_events = []
            for event in group_events:
                if user == event.user:
                    continue  # users don't receive infos about events they caused
                if not (('%d__%s' % (event.group_id, ALL_NOTIFICATIONS_ID) in wanted_group_notifications) or \
                        ('%d__%s' % (event.group_id, event.notification_id) in wanted_group_notifications)):
                    continue  # must have an actual subscription to that event type
                if event.target_object is None:
                    continue  # referenced object has been deleted by now
                if not check_object_read_access(event.target_object, user):
                    continue  # user must be able to even see referenced object 
                wanted_group_events.append(event)
                
            
            group_html = '\n'.join([render_digest_item_for_notification_event(event, user) for event in wanted_group_events])
            group_template_context = {
                'group_html': mark_safe(group_html),
                'group': group,
            }
            # TODO: create a group-layout template with group header and a fill-in for the single 
            #body_html += render_to_string('cosinnus/path/to/body/template', context=group_template_context) + '\n'
            body_html += group_html + '\n'
        
        # send actual email with full frame template
        _send_digest_email(user, mark_safe(body_html), TIME_DIGEST_END, digest_setting)
        emailed += 1
    
    deleted = cleanup_stale_notifications()
    
    extra_log = {
        'users_emailed': emailed,
        'total_users': len(users),
        'delted_stale_notifications': deleted,
        'fresh_notifications_alive': NotificationEvent.objects.all().count(),
    }
    logger.info('Finished sending out digests of SETTING=%s. Data in extra.' % UserNotificationPreference.SETTING_CHOICES[digest_setting][1], extra=extra_log)
    if settings.DEBUG:
        print extra_log
    

def render_digest_item_for_notification_event(notification_event, receiver):
    """ Renders the HTML of a single notification event for a receiving user """
    
    # TODO: stub for rendering the notification based on the registered notifications 
    # and their templates defined in cosinnus_notifications.py
    obj = notification_event.target_object
    
    return '<div>stub: event "%s" with object "%s" from user "%s"</div>' % (
        notification_event.notification_id,
        getattr(obj, 'text', getattr(obj, 'title', getattr(obj, 'name', 'NOARGS'))),
        notification_event.user.get_full_name(),
    )


def _send_digest_email(receiver, body_html, digest_generation_time, digest_setting):
    
    # switch language to user's preference language
    cur_language = translation.get_language()
    try:
        translation.activate(getattr(receiver.cosinnus_profile, 'language', settings.LANGUAGES[0][0]))
        
        # TODO: FIXME:
        print ">> now sending HTML to user", receiver.get_full_name()
        print body_html
        return
        
        
        template = '/path/to/digest/mail/template' # TODO
        subj_template = '/path/to/digest/mail/template' # TODO
        site = CosinnusPortal.get_current().site
        context = {
            'site': site,
            'site_name': site.name,
            'domain_url': CosinnusPortal.get_current().get_domain,
        }
        preference_url = '%s%s' % (context['domain_url'], reverse('cosinnus:notifications'))
        context.update({
            'receiver': receiver, 
            'receiver_name': mark_safe(strip_tags(full_name(receiver))), 
            'notification_settings_url': mark_safe(preference_url),
            'body_html': mark_safe(body_html),
            'digest_time': digest_generation_time, # TODO: humanize
            'digest_setting': digest_setting,
        })
        subject = render_to_string(subj_template, context)
        send_mail_or_fail(receiver.email, subject, template, context)
        
    finally:
        translation.activate(cur_language)


def cleanup_stale_notifications():
    """ Deletes all notification events that will never be used again to compose a digest. 
    
        This deletes all notification events that have been created more than 3x the length 
        of the longest digest period ago. I.e. if our longest digest is 1 week, this will delete
        all items older than 21 days. This is a naive safety measure to prevent multiple digests
        running at the same time to delete each other's notification events from under them.
        
        @return the count of the items deleted """
        
    max_days = max(dict(UserNotificationPreference.SETTINGS_DAYS_DURATIONS).values())
    time_digest_stale = now() - timedelta(days=max_days*3)
    stale_notification_events = NotificationEvent.objects.filter(date__lt=time_digest_stale)
    
    deleted = stale_notification_events.count()
    stale_notification_events.delete()
    return deleted
