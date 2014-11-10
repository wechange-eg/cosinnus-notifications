# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.template.loader import render_to_string

from cosinnus.conf import settings
from cosinnus.core.mail import send_mail
from django.contrib.sites.models import get_current_site
from django.utils.encoding import force_text

#send_mail

def _mail_print(to, subject, template, data, from_email=None, bcc=None):
    print ">> Mail printing:"
    print ">> To: ", to
    print ">> Subject: ", force_text(subject)
    print ">> Body:"
    print render_to_string(template, data)
    
def send_mail_or_fail(to, subject, template, data, from_email=None, bcc=None):
    try:
        send_mail(to, subject, template, data, from_email, bcc)
    except:
        # FIXME: fail silently. better than erroring on the user. should be logged though!
        if settings.DEBUG:
            _mail_print(to, subject, template, data, from_email, bcc)
    

def get_common_mail_context(request, group=None, user=None):
    """ Collects common context variables for Email templates """
    
    site = get_current_site(request)
    context = {
        'site': site,
        'site_name': site.name,
        'protocol': request.is_secure() and 'https' or 'http'
    }
    if group:
        context.update({
            'group_name': group.name,
            'group': group,
        })
    if user:
        context.update({
            'user_name': user.get_full_name() or user.get_username(),
            'user': user,
        })
    return context
        

