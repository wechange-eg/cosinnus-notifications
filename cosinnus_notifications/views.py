# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.core.urlresolvers import reverse_lazy
from django.contrib import messages
from django.http.response import HttpResponseRedirect
from django.utils.translation import ugettext_lazy as _
from django.views.generic.edit import UpdateView

from cosinnus.core.decorators.views import require_logged_in
from cosinnus_notifications.models import UserNotificationPreference
from cosinnus_notifications.notifications import notifications,\
    ALL_NOTIFICATIONS_ID, NO_NOTIFICATIONS_ID,\
    set_user_group_notifications_special


class NotificationPreferenceView(UpdateView):
    
    object = {}
    model = UserNotificationPreference
    template_name = 'cosinnus_notifications/notifications_form.html'
    success_url = reverse_lazy('cosinnus:notifications')
    message_success = _('Your notification preferences were updated successfully.')
    
    @require_logged_in()
    def dispatch(self, request, *args, **kwargs):
        return super(NotificationPreferenceView, self).dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """
        Handles GET requests and instantiates a blank version of the form.
        """
        self.user = self.request.user
        return self.render_to_response(self.get_context_data())
    
    def post(self, request, *args, **kwargs):
        """
        Handles POST requests, instantiating a form instance with the passed
        POST variables and then checked for validity.
        """
        for name, value in request.POST.items():
            # we go through all values POSTed to us. some of these are the settings from the dropdown
            # box (all / none / custom), some of them are the individual custom preference choices
            # for a group.
            # depending of the dropdown setting we set the global all/none setting and ignore the custom
            # values, or if set to custom, delete any global all/none preference entries for that group
            # and save the individual preference settings for that group
            if not name.startswith('notif_'):
                continue
            if name.startswith('notif_choice:'):
                group_id = int(name.split(':')[1])
                group = CosinnusGroup.objects.get_cached(pks=group_id)
                set_user_group_notifications_special(request.user, group, value)
            elif name.startswith('notif_option:'):
                # if we are looking at a group item, check if the choice field is set to custom,
                # otherwise ignore it
                print ">>> splitting", name, value
                value = int(value)
                _, group_id, notification_id = name.split(':')
                if request.POST.get('notif_choice:%s' % group_id, None) == 'custom':
                    # save custom settings if the main switch for custom is enabled:
                    group = CosinnusGroup.objects.get_cached(pks=int(group_id))
                    # save / erase setting
                    try:
                        pref = UserNotificationPreference.objects.get(user=request.user, group=group, notification_id=notification_id)
                        if value == 1 and not pref.is_active:
                            pref.is_active = True
                            pref.save()
                            print ">>> saved to yes"
                        elif value == 0 and pref.is_active:
                            pref.is_active = False
                            pref.save()
                            print ">>> saved to no"
                    except:
                        pref = UserNotificationPreference.objects.create(user=request.user, group=group, notification_id=notification_id, is_active=value)
                        print ">>> created", pref, value
                    
                else:
                    print ">> ignoring non-custom field ", name
        
        messages.success(request, self.message_success)
        return HttpResponseRedirect(self.success_url)
    
    def get_queryset(self):
        """
            Get the queryset of notifications
        """
        self.queryset = self.model._default_manager.filter(user=self.request.user)
        return self.queryset
    
    def get_context_data(self, **kwargs):
        """
        Insert the single object into the context dict.
        """
        context = super(UpdateView, self).get_context_data(**kwargs)
        
        # build lookup dict for all active existing preferences vs groups
        prefs = {} # 'groupid:notification_id' 
        for pref in self.get_queryset():
            prefs['%s:%s' % (pref.group.pk, pref.notification_id)] = pref.is_active
        
        group_rows = [] # [(group, notification_rows, choice_selected), ...]
        # get groups, grouped by their 
        groups = CosinnusGroup.objects.get_for_user(self.user)
        groups = sorted(groups, key=lambda group: ((group.parent.name +'_' if group.parent else '') + group.name).lower())
        
        for group in groups:
            choice_selected = "custom"
            notification_rows = [] # [[id, label, value], ...]
            for notification_id, options in notifications.items():
                notif_id = '%s:%s' % (group.pk, notification_id)
                if notification_id == ALL_NOTIFICATIONS_ID:
                    if notif_id in prefs:
                        choice_selected = "all"
                    continue
                if notification_id == NO_NOTIFICATIONS_ID:
                    if notif_id in prefs:
                        choice_selected = "none"
                    continue
                if notif_id in prefs:
                    active = bool(prefs[notif_id])
                else:
                    active = options.get('default', False)
                # check for default if false, 
                notification_rows.append([notif_id, options['label'], active])
            group_rows.append( (group, notification_rows, choice_selected) )
        
        context.update({
            #'object_list': self.queryset,
            'grouped_notifications': group_rows,
            'user': self.request.user,
            'all_notifications_id': ALL_NOTIFICATIONS_ID,
            'no_notifications_id': NO_NOTIFICATIONS_ID,
        })
        return context
    
    
notification_preference_view = NotificationPreferenceView.as_view()

    