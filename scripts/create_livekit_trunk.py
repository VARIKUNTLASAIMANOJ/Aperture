"""
Create the LiveKit outbound SIP trunk that points at your Twilio trunk.

This is the object whose id goes in LIVEKIT_SIP_TRUNK_ID. It does not exist
until you create it — a LiveKit project has no trunks by default, and the
`*.sip.livekit.cloud` hostname shown in the LiveKit console is an endpoint
address, not a trunk.

Prerequisites, all from the Twilio console (see docs/VOICE_AGENT.md):
  * an Elastic SIP Trunk with Termination enabled
  * its Termination SIP URI, e.g. my-trunk.pstn.twilio.com
  * a Credential List username and password on that trunk
  * your Twilio phone number assigned to it, in E.164

Usage:
    python3 -m scripts.create_livekit_trunk \\
        --address  my-trunk.pstn.twilio.com \\
        --number   +15551234567 \\
        --username my-sip-user

The password is read from the TWILIO_SIP_PASSWORD environment variable, or
prompted for — never passed as an argument, where it would land in your shell
history and in `ps` output.

    python3 -m scripts.create_livekit_trunk --list     # show existing trunks
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()

E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _api():
    from livekit import api

    missing = [k for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
               if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    return api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )


async def list_trunks() -> None:
    from livekit import api

    lk = _api()
    try:
        out = await lk.sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        if not out.items:
            print("No outbound trunks in this project yet.")
        for t in out.items:
            print(f"  {t.sip_trunk_id}  name={t.name!r}  address={t.address}  "
                  f"numbers={list(t.numbers)}")
            print(f"    → LIVEKIT_SIP_TRUNK_ID={t.sip_trunk_id}")
    finally:
        await lk.aclose()


async def create(address: str, number: str, username: str, password: str,
                 name: str) -> None:
    from livekit import api

    lk = _api()
    try:
        trunk = await lk.sip.create_sip_outbound_trunk(
            api.CreateSIPOutboundTrunkRequest(
                trunk=api.SIPOutboundTrunkInfo(
                    name=name,
                    address=address,
                    # Twilio requires the caller id to be a number you own on
                    # that trunk; it is also what the candidate sees.
                    numbers=[number],
                    auth_username=username,
                    auth_password=password,
                )
            )
        )
    finally:
        await lk.aclose()

    print(f"\nCreated outbound trunk: {trunk.sip_trunk_id}")
    print("\nPut this in your .env, replacing the current value:\n")
    print(f"    LIVEKIT_SIP_TRUNK_ID={trunk.sip_trunk_id}")
    print("\nThen restart the API (editing .env does not trigger --reload) and")
    print("confirm with:  curl -s localhost:8000/voice/status")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="list existing trunks and exit")
    p.add_argument("--address", help="Twilio Termination SIP URI, e.g. my-trunk.pstn.twilio.com")
    p.add_argument("--number", help="your Twilio number in E.164, e.g. +15551234567")
    p.add_argument("--username", help="Twilio SIP credential-list username")
    p.add_argument("--name", default="twilio-outbound", help="a label for the trunk")
    args = p.parse_args()

    if args.list:
        asyncio.run(list_trunks())
        return

    if not (args.address and args.number and args.username):
        p.error("--address, --number and --username are all required (or use --list)")

    if not E164.match(args.number):
        p.error(f"--number must be E.164, e.g. +15551234567 (got {args.number!r})")

    address = args.address.replace("sip:", "").strip().rstrip("/")
    if ".sip.livekit.cloud" in address:
        p.error(
            f"{address!r} is LiveKit's own SIP endpoint, not your Twilio trunk. "
            f"You want the Termination SIP URI from Twilio → Elastic SIP "
            f"Trunking → your trunk → Termination, which ends in "
            f".pstn.twilio.com"
        )

    password = os.environ.get("TWILIO_SIP_PASSWORD") or getpass.getpass(
        "Twilio SIP credential password (not echoed): ")
    if not password:
        sys.exit("A password is required.")

    asyncio.run(create(address, args.number, args.username, password, args.name))


if __name__ == "__main__":
    main()
