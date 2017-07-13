"""
Tasks for the messages application.
"""

from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from celery.schedules import crontab
from celery.task import periodic_task, task
from dateutil.relativedelta import relativedelta
import logging
import stripe

from muckrock.accounts.models import Profile
from muckrock.message.email import TemplateEmail
from muckrock.message.notifications import SlackNotification
from muckrock.message import digests, receipts
from muckrock.organization.models import Organization
from muckrock.utils import stripe_retry_on_error

logger = logging.getLogger(__name__)

@task(name='muckrock.message.tasks.send_activity_digest')
def send_activity_digest(user, subject, interval):
    """Individual task to create and send an activity digest to a user."""
    email = digests.ActivityDigest(
        user=user,
        subject=subject,
        interval=interval,
    )
    email.send()

def send_digests(preference, subject, interval):
    """Helper to send out timed digests"""
    users = (User.objects
            .filter(
                profile__email_pref=preference,
                notifications__read=False,
                )
            .distinct()
            )
    for user in users:
        send_activity_digest.delay(user, subject, interval)

# every hour
@periodic_task(run_every=crontab(hour='*/1', minute=0), name='muckrock.message.tasks.hourly_digest')
def hourly_digest():
    """Send out hourly digest"""
    send_digests('hourly', u'Hourly Digest', relativedelta(hours=1))

# every day at 10am
@periodic_task(run_every=crontab(hour=10, minute=0), name='muckrock.message.tasks.daily_digest')
def daily_digest():
    """Send out daily digest"""
    send_digests('daily', u'Daily Digest', relativedelta(days=1))

# every Monday at 10am
@periodic_task(
    run_every=crontab(day_of_week=1, hour=10, minute=0),
    name='muckrock.message.tasks.weekly_digest')
def weekly_digest():
    """Send out weekly digest"""
    send_digests('weekly', u'Weekly Digest', relativedelta(weeks=1))

# first day of every month at 10am
@periodic_task(
    run_every=crontab(day_of_month=1, hour=10, minute=0),
    name='muckrock.message.tasks.monthly_digest')
def monthly_digest():
    """Send out monthly digest"""
    send_digests('monthly', u'Monthly Digest', relativedelta(months=1))

# every day at 9:30am
@periodic_task(run_every=crontab(hour=9, minute=30), name='muckrock.message.tasks.staff_digest')
def staff_digest():
    """Send out staff digest"""
    staff_users = User.objects.filter(is_staff=True).distinct()
    for staff_user in staff_users:
        email = digests.StaffDigest(user=staff_user, subject=u'Daily Staff Digest')
        email.send()

@task(name='muckrock.message.tasks.send_invoice_receipt')
def send_invoice_receipt(invoice_id):
    """Send out a receipt for an invoiced charge"""
    invoice = stripe_retry_on_error(
            stripe.Invoice.retrieve,
            invoice_id,
            )
    try:
        charge = stripe_retry_on_error(
                stripe.Charge.retrieve,
                invoice.charge,
                )
    except stripe.error.InvalidRequestError:
        # a free subscription has no charge attached
        # maybe send a notification about the renewal
        # but for now just handle the error
        return
    profile = Profile.objects.get(customer_id=invoice.customer)
    # send a receipt based on the plan
    customer = profile.customer()
    subscription = customer.subscriptions.retrieve(invoice.subscription)
    try:
        receipt_functions = {
            'pro': receipts.pro_subscription_receipt,
            'org': receipts.org_subscription_receipt
        }
        receipt_function = receipt_functions[subscription.plan.id]
    except KeyError:
        logger.warning('Invoice charged for unrecognized plan: %s', subscription.plan.name)
        receipt_function = receipts.generic_receipt
    receipt = receipt_function(profile.user, charge)
    receipt.send(fail_silently=False)

@task(name='muckrock.message.tasks.send_charge_receipt')
def send_charge_receipt(charge_id):
    """Send out a receipt for a charge"""
    charge = stripe_retry_on_error(
            stripe.Charge.retrieve,
            charge_id,
            )
    # if the charge was generated by an invoice, let the invoice handler send the receipt
    if charge.invoice:
        return
    # we should expect charges to have metadata attached when they are made
    try:
        user_email = charge.metadata['email']
        user_action = charge.metadata['action']
    except KeyError:
        logger.warning('Malformed charge metadata, no receipt sent: %s', charge)
        return
    # try getting the user based on the provided email
    # we know from Checkout purchases that logged in users have their email autofilled
    try:
        user = User.objects.get(email=user_email)
    except User.DoesNotExist:
        user = None
    try:
        receipt_functions = {
            'request-purchase': receipts.request_purchase_receipt,
            'request-fee': receipts.request_fee_receipt,
            'crowdfund-payment': receipts.crowdfund_payment_receipt,
            'donation': receipts.donation_receipt,
        }
        receipt_function = receipt_functions[user_action]
    except KeyError:
        logger.warning('Unrecognized charge: %s', user_action)
        receipt_function = receipts.generic_receipt
    receipt = receipt_function(user, charge)
    receipt.send(fail_silently=False)

def get_subscription_type(invoice):
    """Gets the subscription type from the invoice."""
    # get the first line of the invoice
    lines = invoice.lines
    subscription_type = 'unknown'
    if lines.total_count > 0:
        data = lines.data
        plan = data[0].plan
        subscription_type = plan.id
    return subscription_type

@task(name='muckrock.message.tasks.failed_payment')
def failed_payment(invoice_id):
    """Notify a customer about a failed subscription invoice."""
    invoice = stripe_retry_on_error(
            stripe.Invoice.retrieve,
            invoice_id,
            )
    attempt = invoice.attempt_count
    subscription_type = get_subscription_type(invoice)
    profile = Profile.objects.get(customer_id=invoice.customer)
    user = profile.user
    # raise the failed payment flag on the profile
    profile.payment_failed = True
    profile.save()
    subject = u'Your payment has failed'
    org = None
    if subscription_type == 'org':
        org = Organization.objects.get(owner=user)
    if attempt == 4:
        # on last attempt, cancel the user's subscription and lower the failed payment flag
        if subscription_type == 'pro':
            profile.cancel_pro_subscription()
        elif subscription_type == 'org':
            org.cancel_subscription()
        profile.payment_failed = False
        profile.save()
        logger.info('%s subscription has been cancelled due to failed payment', user.username)
        subject = u'Your %s subscription has been cancelled' % subscription_type
        context = {
            'attempt': 'final',
            'type': subscription_type,
            'org': org
        }
    else:
        logger.info('Failed payment by %s, attempt %s', user.username, attempt)
        context = {
            'attempt': attempt,
            'type': subscription_type,
            'org': org
        }
    notification = TemplateEmail(
        user=user,
        extra_context=context,
        text_template='message/notification/failed_payment.txt',
        html_template='message/notification/failed_payment.html',
        subject=subject,
    )
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.welcome')
def welcome(user):
    """Send a welcome notification to a new user. Hello!"""
    verification_url = reverse('acct-verify-email')
    key = user.profile.generate_confirmation_key()
    context = {'verification_link': user.profile.wrap_url(verification_url, key=key)}
    notification = TemplateEmail(
        user=user,
        extra_context=context,
        text_template='message/notification/welcome.txt',
        html_template='message/notification/welcome.html',
        subject=u'Welcome to MuckRock!'
    )
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.welcome_miniregister')
def welcome_miniregister(user):
    """Send a welcome notification to a new users who signed up with miniregister.
    Provide them a link to verify their email and update their username/password."""
    completion_url = reverse('accounts-complete-registration')
    key = user.profile.generate_confirmation_key()
    context = {'completion_url': user.profile.wrap_url(completion_url, key=key)}
    notification = TemplateEmail(
        user=user,
        extra_context=context,
        text_template='message/notification/welcome_miniregister.txt',
        html_template='message/notification/welcome_miniregister.html',
        subject=u'Welcome to MuckRock!'
    )
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.gift')
def gift(to_user, from_user, gift_description):
    """Notify the user when they have been gifted requests."""
    context = {
        'from': from_user,
        'gift': gift_description
    }
    notification = TemplateEmail(
        user=to_user,
        extra_context=context,
        text_template='message/notification/gift.txt',
        html_template='message/notification/gift.html',
        subject=u'You got a gift!'
    )
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.email_change')
def email_change(user, old_email):
    """Notify the user when their email is changed."""
    context = {
        'old_email': old_email,
        'new_email': user.email
    }
    notification = TemplateEmail(
        user=user,
        extra_context=context,
        text_template='message/notification/email_change.txt',
        html_template='message/notification/email_change.html',
        subject=u'Changed email address'
    )
    notification.to.append(old_email) # Send to both the new and old email addresses
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.email_verify')
def email_verify(user):
    """Verify the user's email by sending them a message."""
    url = reverse('acct-verify-email')
    key = user.profile.generate_confirmation_key()
    context = {
        'verification_link': user.profile.wrap_url(url, key=key)
    }
    notification = TemplateEmail(
        user=user,
        extra_context=context,
        text_template='message/notification/email_verify.txt',
        html_template='message/notification/email_verify.html',
        subject=u'Verify your email'
    )
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.support')
def support(user, message, _task):
    """Send a response to a user about a task."""
    context = {
        'message': message,
        'task': _task
    }
    notification = TemplateEmail(
        user=user,
        extra_context=context,
        text_template='message/notification/support.txt',
        html_template='message/notification/support.html',
        subject=u'Support #%d' % _task.id
    )
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.notify_project_contributor')
def notify_project_contributor(user, project, added_by):
    """Notify a user that they were added as a contributor to a project."""
    context = {
        'project': project,
        'added_by': added_by
    }
    notification = TemplateEmail(
        user=user,
        extra_context=context,
        text_template='message/notification/project.txt',
        html_template='message/notification/project.html',
        subject=u'Added to a project'
    )
    notification.send(fail_silently=False)

@task(name='muckrock.message.tasks.slack')
def slack(payload):
    """Send a Slack notification using the provided payload."""
    notification = SlackNotification(payload)
    notification.send()
