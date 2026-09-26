"""Play the payment provider: send a signed webhook event to the API.

    python -m scripts.send_webhook <provider_ref> SUCCESS|FAILED [--event-id evt_123] [--url http://localhost:8000]

Sending the same --event-id twice shows the idempotency handling.
"""

import argparse
import json
import urllib.error
import urllib.request
import uuid

from app.security import sign_webhook_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("provider_ref")
    parser.add_argument("status", choices=["SUCCESS", "FAILED"])
    parser.add_argument("--event-id", default=f"evt_{uuid.uuid4().hex[:12]}")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    body = json.dumps({"event_id": args.event_id, "provider_ref": args.provider_ref, "status": args.status}).encode()
    request = urllib.request.Request(
        f"{args.url}/payments/webhook/",
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sign_webhook_payload(body)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            print(response.status, response.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.code, exc.read().decode())


if __name__ == "__main__":
    main()
