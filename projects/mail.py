from datetime import timedelta
from typing import List, Dict, Any
import os

from django.conf import settings
from django.core.mail import send_mail as django_send_mail, EmailMultiAlternatives
from django.utils import timezone
from django_q.tasks import async_task

import logging
from jinja2 import Environment, FileSystemLoader

from projects.models.project import EmailMessage, EmailTemplate
from users.models import User

log = logging.getLogger(__name__)


class MailException(Exception):
    pass


def _send_template_message(email: str, subject: str, message: str, template: EmailTemplate, context: Dict[str, Any] = None):
    """
    Render email template using Jinja2

    Args:
        email: Recipient email address
        subject: Email subject line
        message: Plain text message body
        template: EmailTemplate object containing the HTML file
        context: Dictionary of variables to use in template rendering

    Raises:
        MailException: If template rendering or email sending fails
    """

    # If no context is given, default to subject and message
    if context is None or (isinstance(context, dict) and len(context.items()) == 0):
        context = {"subject": subject, "message": message}

    try:
        # Read the template file
        template_path = template.file.path

        # Get the directory and filename
        template_dir = os.path.dirname(template_path)
        template_filename = os.path.basename(template_path)

        # Create Jinja2 environment with the template directory
        jinja_env = Environment(loader=FileSystemLoader(template_dir))
        template = jinja_env.get_template(template_filename)

        # Render the template with context
        html_message = template.render(**context)

        # Send the email with rendered HTML
        _send_message(email, subject, message, html_message)

    except Exception as e:
        log.error(f"Failed to render template {template.name} for {email}: {str(e)}")
        # Create EmailMessage and save it for re-try later
        EmailMessage.objects.create(
            recipient=email,
            subject=subject,
            message=message,
            template=template,
            context=context,
            scheduled_time=timezone.now() + timedelta(minutes=5)
        )
        raise MailException(f"Failed to render template: {str(e)}")


# TODO implement attachments when (if) needed
def _send_message(email: str, subject: str, message: str, html_message: str = None):
    """
    Send message using Django's email backend.
    Private module-level function - should only be called via async_task.

    Args:
        email: Recipient email address
        subject: Email subject line
        message: Plain text message body
        html_message: Optional HTML message body

    Raises:
        MailException: If email sending fails
    """
    try:
        if html_message:
            # Send multipart email with both plain text and HTML
            msg = EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email]
            )
            msg.attach_alternative(html_message, "text/html")
            msg.send(fail_silently=False)
            log.info(f"HTML email sent to {email}: {subject}")
        else:
            # Send plain text email
            django_send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False
            )
            log.info(f"Email sent to {email}: {subject}")
    except Exception as e:
        log.error(f"Failed to send email to {email}: {str(e)}")
        # Create EmailMessage and save it for re-try later
        EmailMessage.objects.create(
            recipient=email,
            subject=subject,
            message=message,
            scheduled_time=timezone.now() + timedelta(minutes=5)
        )
        raise MailException(f"Failed to send email: {str(e)}")


class MailClient:

    HOST: str = None
    PORT: int = None
    ENVIRONMENT: str = None
    WHITELIST: List[str] = None

    def __init__(self):
        if not settings.EMAIL_HOST and not settings.EMAIL_PORT:
            log.warning("EMAIL_HOST and EMAIL_PORT not defined in settings -- Mail Client not enabled")
            return
        if not settings.EMAIL_ENVIRONMENT:
            log.warning("EMAIL_ENVIRONMENT not defined in settings -- Mail Client not enabled")
            return
        self.ENVIRONMENT = settings.EMAIL_ENVIRONMENT
        self.WHITELIST = settings.EMAIL_WHITELIST

    # --- General ---

    def send_email_message(self, email_message: EmailMessage):
        if email_message.template:
            self.send_template_to_email(email_message.recipient, email_message.subject, email_message.message, email_message.template, email_message.context)
        else:
            self.send_message_to_email(email_message.recipient, email_message.subject, email_message.message)

    # --- Template email functions ---

    def send_template_to_users(self, recipients: List[User], subject: str, message: str, template: EmailTemplate, context: Dict[str, Any] = None):
        for recipient in recipients:
            self.send_template_to_user(recipient, subject, message, template, context)

    def send_template_to_user(self, recipient: User, subject: str, message: str, template: EmailTemplate, context: Dict[str, Any] = None):
        self.send_template_to_email(recipient.email, subject, message, template, context)

    def send_template_to_emails(self, emails: List[str], subject: str, message: str, template: EmailTemplate, context: Dict[str, Any] = None):
        for email in emails:
            self.send_template_to_email(email, subject, message, template, context)

    def send_template_to_email(self, email: str, subject: str, message: str, template: EmailTemplate, context: Dict[str, Any] = None):
        if self.ENVIRONMENT == "production" or email.lower() in self.WHITELIST:
            async_task('projects.mail._send_template_message', email, subject, message, template, context)
        else:
            log.info(f"Email not sent to {email} (environment: {self.ENVIRONMENT}, not in whitelist)")

    # --- Plain text email functions ---

    def send_message_to_users(self, users: List[User], subject: str, message: str):
        for user in users:
            self.send_message_to_user(user, subject, message)

    def send_message_to_user(self, user: User, subject: str, message: str):
        self.send_message_to_email(user.email, subject, message)

    # TODO imlpement send_mass_mail() is there is need in the future, kept simple for now
    def send_message_to_emails(self, emails: List[str], subject: str, message: str):
        for email in emails:
            self.send_message_to_email(email, subject, message)

    def send_message_to_email(self, email: str, subject: str, message: str):
        if self.ENVIRONMENT == "production" or email.lower() in self.WHITELIST:
            async_task('projects.mail._send_message', email, subject, message)
        else:
            log.info(f"Email not sent to {email} (environment: {self.ENVIRONMENT}, not in whitelist)")

mail_client = MailClient()