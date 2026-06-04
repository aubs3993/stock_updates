"""Send the digest via the Resend transactional email API.

One POST to RESEND_SEND_URL with a Bearer EMAIL_API_KEY. To switch providers,
this module is the only place that needs to change.
"""

import requests

from . import config


def send(api_key, sender, recipient, subject, html_body, text_body):
    """Send one email. Returns the provider response dict; raises on failure."""
    resp = requests.post(
        config.RESEND_SEND_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        },
        timeout=config.EMAIL_TIMEOUT_SECONDS,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"email send failed: HTTP {resp.status_code} — {resp.text[:500]}"
        )
    return resp.json()
