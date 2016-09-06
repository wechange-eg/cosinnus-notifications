# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import timedelta
import logging

from django.contrib.auth import get_user_model
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.encoding import force_text
from django.utils import translation
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _

from cosinnus.conf import settings
from cosinnus.models.group import CosinnusPortal
from cosinnus_notifications.models import UserNotificationPreference,\
    NotificationEvent
from cosinnus_notifications.notifications import NO_NOTIFICATIONS_ID,\
    ALL_NOTIFICATIONS_ID, notifications, NOTIFICATION_REASONS
from cosinnus.templatetags.cosinnus_tags import full_name, cosinnus_setting
from cosinnus.core.mail import send_mail_or_fail
from cosinnus.utils.permissions import check_object_read_access
import traceback
from django.templatetags.static import static
from cosinnus.utils.functions import resolve_attributes

logger = logging.getLogger('cosinnus')


DIGEST_ITEM_TITLE_MAX_LENGTH = 50


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
    
    # read the time for the last sent digest of this time
    # (its saved as a string, but django QS will auto-box it when filtering on datetime fields)
    TIME_DIGEST_START = portal.saved_infos.get(CosinnusPortal.SAVED_INFO_LAST_DIGEST_SENT % digest_setting, None)
    if not TIME_DIGEST_START:
        TIME_DIGEST_START = now() - timedelta(days=UserNotificationPreference.SETTINGS_DAYS_DURATIONS[digest_setting])
    TIME_DIGEST_END = now()
    
    # the main Notification Events QS. anything not in here did not happen in the digest's time span
    timescope_notification_events = NotificationEvent.objects.filter(date__gte=TIME_DIGEST_START, date__lt=TIME_DIGEST_END)
    users = get_user_model().objects.all().filter(id__in=portal.members)
    
    extra_info = {
        'notification_event_count': timescope_notification_events.count(),
        'potential_user_count': users.count(), 
    }
    logger.info('Now starting to sending out digests of SETTING=%s in Portal "%s". Data in extra.' % \
                (UserNotificationPreference.SETTING_CHOICES[digest_setting][1], portal.slug), extra=extra_info)
    if settings.DEBUG:
        print ">> ", extra_info
    
    emailed = 0
    for user in users:
        try:
            # only active users that have logged in before accepted the TOS get notifications
            if not user.is_active or not user.last_login or not cosinnus_setting(user, 'tos_accepted'):
                continue
            
            # these groups will never get digest notifications because they have a blanketing ALL (now) or NONE setting
            # (they may still have individual preferences in the DB, which are ignored because of the blanket setting)
            exclude_digest_groups = UserNotificationPreference.objects.filter(user=user, group_id__in=portal_group_ids) 
            exclude_digest_groups = exclude_digest_groups.filter(Q(notification_id=ALL_NOTIFICATIONS_ID, setting=UserNotificationPreference.SETTING_NOW) | Q(notification_id=NO_NOTIFICATIONS_ID))
            exclude_digest_groups = exclude_digest_groups.values_list('group_id', flat=True)  
            
            # find out any notification preferences the user has for groups in this portal with the daily/weekly setting
            # if he doesn't have any, we will not send a mail for them
            prefs = UserNotificationPreference.objects.filter(user=user, group_id__in=portal_group_ids, setting=digest_setting)
            prefs = prefs.exclude(notification_id=NO_NOTIFICATIONS_ID).exclude(group_id__in=exclude_digest_groups)
            
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
            for group in list(set(events.values_list('group', flat=True))): 
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
                    
                if wanted_group_events:
                    group = wanted_group_events[0].group # needs to be resolved, values_list returns only id ints
                    group_body_html = '\n'.join([render_digest_item_for_notification_event(event, user) for event in wanted_group_events])
                    group_template_context = {
                        'group_body_html': mark_safe(group_body_html),
                        'image_url': CosinnusPortal.get_current().get_domain() + \
                            (group.get_avatar_thumbnail_url() or static('images/group-avatar-placeholder.png')),
                        'group_url': group.get_absolute_url(),
                        'group_name': group['name'],
                    }
                    group_html = render_to_string('cosinnus/html_mail/summary_group.html', context=group_template_context)
                    body_html += group_html + '\n'
            
            # send actual email with full frame template
            _send_digest_email(user, mark_safe(body_html), TIME_DIGEST_END, digest_setting)
            emailed += 1
            
        except Exception, e:
            # we never want this subroutine to just die, we need the final saves at the end to ensure
            # the same items do not get into digests twice
            logger.error('An error occured while doing a digest for a user! Exception was: %s' % force_text(e), 
                         extra={'exception': e, 'trace': traceback.format_exc(), 'user_mail': user.email, 'digest_setting': digest_setting})
            if settings.DEBUG:
                raise
            
    # save the end time of the digest period as last digest time for this type
    portal.saved_infos[CosinnusPortal.SAVED_INFO_LAST_DIGEST_SENT % digest_setting] = TIME_DIGEST_END
    portal.save()
    
    deleted = cleanup_stale_notifications()
    
    extra_log = {
        'users_emailed': emailed,
        'total_users': len(users),
        'deleted_stale_notifications': deleted,
        'remaining_past_and_future_notifications': NotificationEvent.objects.all().count(),
    }
    logger.info('Finished sending out digests of SETTING=%s in Portal "%s". Data in extra.' % (UserNotificationPreference.SETTING_CHOICES[digest_setting][1], portal.slug), extra=extra_log)
    if settings.DEBUG:
        print extra_log
    

def render_digest_item_for_notification_event(notification_event, receiver):
    """ Renders the HTML of a single notification event for a receiving user """
    
    try:
        obj = notification_event.target_object
        options = notifications[notification_event.notification_id]
        
        # stub for missing notification for this digest
        if not options.get('is_html', False):
            logger.exception('Missing HTML snippet for digest encountered for notification setting "%s". Skipping this notification type in this digest!' % notification_event.notification_id)
            return ''
            """
            return '<div>stub: event "%s" with object "%s" from user "%s"</div>' % (
                notification_event.notification_id,
                getattr(obj, 'text', getattr(obj, 'title', getattr(obj, 'name', 'NOARGS'))),
                notification_event.user.get_full_name(),
            )
            """
        data_attributes = options['data_attributes']
        
        string_variables = {
            'sender_name': mark_safe(strip_tags(full_name(receiver))),
        }
        event_text = options['event_text']
        sub_event_text = resolve_attributes(obj, data_attributes['sub_event_text'])
        event_text = (event_text % string_variables) if event_text else None
        sub_event_text = (sub_event_text % string_variables) if sub_event_text else None
        
        data = {
            'type': options['snippet_type'],
            'event_text': event_text,
            'snippet_template': options['snippet_template'],
            
            'event_meta': resolve_attributes(obj, data_attributes['event_meta']),
            'object_name': resolve_attributes(obj, data_attributes['object_name'], 'title'),
            'object_url': resolve_attributes(obj, data_attributes['object_url'], 'get_absolute_url'),
            'object_text': resolve_attributes(obj, data_attributes['object_text']),
            'image_url': resolve_attributes(obj, data_attributes['image_url']),
            
            'sub_event_text': sub_event_text,
            'sub_event_meta': resolve_attributes(obj, data_attributes['sub_image_url']),
            'sub_image_url': resolve_attributes(obj, data_attributes['sub_image_url']),
            'sub_object_text': resolve_attributes(obj, data_attributes['sub_object_text']),
        }
        # clean some attributes
        if not data['object_name']:
            data['object_name'] = _('Untitled')
        if len(data['object_name']) > DIGEST_ITEM_TITLE_MAX_LENGTH:
            data['object_name'] = data['object_name'][:DIGEST_ITEM_TITLE_MAX_LENGTH-3] + '...'
        if not data['image_url']:
            # default for image_url is the notifcation event's causer
            data['image_url'] = CosinnusPortal.get_current().get_domain() + \
                 (notification_event.user.cosinnus_profile.get_avatar_thumbnail_url() or static('images/jane-doe.png'))
            
        item_html = render_to_string(options['snippet_template'], context=data)
        return item_html
    
    except Exception, e:
        logger.exception('Error while rendering a digest item for a digest email. Exception in extra.', extra={'exception': force_text(e)})
    return ''

def _send_digest_email(receiver, body_html, digest_generation_time, digest_setting):
    
    # switch language to user's preference language
    cur_language = translation.get_language()
    try:
        translation.activate(getattr(receiver.cosinnus_profile, 'language', settings.LANGUAGES[0][0]))
        
        template = '/cosinnus/html_mail/digest.html' # TODO
        portal_name =  _(settings.COSINNUS_BASE_PAGE_TITLE_TRANS)
        if digest_setting == UserNotificationPreference.SETTING_DAILY:
            subject = _('Your daily digest for %(portal_name)s') % {'portal_name': portal_name}
            topic = _('This is what happened during the last day!')
            reason = NOTIFICATION_REASONS['daily_digest']
        else:
            subject = _('Your weekly digest for %(portal_name)s') % {'portal_name': portal_name}
            topic = _('This is what happened during the last week!')
            reason = NOTIFICATION_REASONS['weekly_digest']
        portal = CosinnusPortal.get_current()
        site = portal.site
        domain = portal.get_domain()
        preference_url = '%s%s' % (domain, reverse('cosinnus:notifications'))
        portal_image_url = '%s%s' % (domain, static('img/logo-icon.png'))
        
        context = {
            'site': site,
            'site_name': site.name,
            'domain_url': domain,
            'portal_url': domain,
            'portal_image_url': portal_image_url,
            'portal_name': portal_name,
            'receiver': receiver, 
            'addressee': mark_safe(strip_tags(full_name(receiver))), 
            'topic': topic,
            'digest_body_html': mark_safe(body_html),
            'prefs_url': mark_safe(preference_url),
            'notification_reason': reason,
            'digest_setting': digest_setting,
            #'digest_time': digest_generation_time, # TODO: humanize
        }
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
