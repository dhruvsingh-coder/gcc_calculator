import azure.functions as func
import json
import random
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import os
import logging
import time
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Store OTPs in memory (use Azure Redis Cache in production)
otp_storage = {}

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    
    try:
        req_body = req.get_json()
        email = req_body.get('email', '').lower().strip()
        organization = req_body.get('organization', '').strip()

        if not email or not organization:
            return func.HttpResponse(
                json.dumps({"error": "Email and organization are required"}),
                status_code=400,
                mimetype="application/json"
            )

        # Validate email format
        if not is_valid_email(email):
            return func.HttpResponse(
                json.dumps({"error": "Please enter a valid email address"}),
                status_code=400,
                mimetype="application/json"
            )

        # Check if email is from personal domain (block these)
        if is_personal_email(email):
            return func.HttpResponse(
                json.dumps({"error": "Please use your company/organization email address. Personal email addresses like Gmail, Yahoo, etc. are not allowed."}),
                status_code=400,
                mimetype="application/json"
            )

        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        otp_storage[email] = {
            'otp': otp,
            'organization': organization,
            'attempts': 0,
            'timestamp': time.time()
        }

        # Send OTP email using SendGrid
        send_otp_email_sendgrid(email, otp, organization)

        return func.HttpResponse(
            json.dumps({"message": "OTP sent successfully"}),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error sending OTP: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Failed to send OTP. Please try again."}),
            status_code=500,
            mimetype="application/json"
        )

def is_valid_email(email):
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def is_personal_email(email):
    """Check if email is from personal domain (Gmail, Yahoo, etc.)"""
    domain = email.split('@')[1] if '@' in email else ''
    
    # List of personal email domains to BLOCK
    personal_domains = [
        # Common personal email providers
        'gmail.com', 'googlemail.com',
        'yahoo.com', 'ymail.com', 'rocketmail.com',
        'hotmail.com', 'outlook.com', 'live.com', 'msn.com',
        'aol.com',
        'icloud.com', 'me.com', 'mac.com',
        'protonmail.com', 'proton.me',
        'zoho.com',
        'mail.com', 'email.com',
        'yandex.com', 'ya.ru',
        'gmx.com', 'gmx.net',
        'fastmail.com',
        'tutanota.com', 'tuta.io',
        'hey.com',
        
        # Indian personal domains
        'rediffmail.com',
        'indiatimes.com',
        
        # Other personal domains
        'inbox.com', 'hushmail.com', 'lavabit.com'
    ]
    
    # Check if domain is in personal domains list
    return domain in personal_domains

def send_otp_email_sendgrid(email, otp, organization):
    """Send OTP email using SendGrid API"""
    sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
    from_email = os.environ.get('SENDGRID_FROM_EMAIL', 'noreply@yourdomain.com')  # Set this in Azure App Settings
    
    if not sendgrid_api_key:
        logging.error("SendGrid API Key not configured")
        # Fallback to SMTP
        send_otp_email_smtp(email, otp, organization)
        return

    try:
        message = Mail(
            from_email=from_email,
            to_emails=email,
            subject='GCC Calculator - Verification Code',
            html_content=create_email_html(otp, organization)
        )
        
        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        
        logging.info(f"SendGrid email sent to {email}. Status: {response.status_code}")
        
    except Exception as e:
        logging.error(f"SendGrid failed for {email}: {str(e)}")
        # Fallback to SMTP
        send_otp_email_smtp(email, otp, organization)

def send_otp_email_smtp(email, otp, organization):
    """Fallback SMTP method"""
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.sendgrid.net')
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_username = os.environ.get('SMTP_USERNAME', 'apikey')
    smtp_password = os.environ.get('SENDGRID_API_KEY')  # For SendGrid SMTP
    
    if not all([smtp_username, smtp_password]):
        logging.warning(f"SMTP not configured. OTP for {email}: {otp}")
        return

    try:
        msg = MimeMultipart()
        msg['From'] = os.environ.get('SMTP_FROM_EMAIL', smtp_username)
        msg['To'] = email
        msg['Subject'] = 'GCC Calculator - Verification Code'
        
        body = create_email_html(otp, organization)
        msg.attach(MimeText(body, 'html'))
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(msg)
        server.quit()
        
        logging.info(f"SMTP OTP sent successfully to {email}")
        
    except Exception as e:
        logging.error(f"Failed to send email to {email}: {str(e)}")
        raise

def create_email_html(otp, organization):
    """Create HTML email content"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(90deg, #FF7F41 0%, #FFA364 100%); color: white; padding: 20px; text-align: center; }}
            .otp {{ font-size: 32px; font-weight: bold; color: #FF7F41; letter-spacing: 5px; text-align: center; margin: 20px 0; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>GCC Setup Cost Calculator</h1>
            </div>
            
            <h2>Email Verification</h2>
            <p>Hello,</p>
            <p>Your verification code for <strong>{organization}</strong> is:</p>
            
            <div class="otp">{otp}</div>
            
            <p>This verification code will expire in 10 minutes.</p>
            <p>If you didn't request this code, please ignore this email.</p>
            
            <div class="footer">
                <p>Best regards,<br><strong>GCC Calculator Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """