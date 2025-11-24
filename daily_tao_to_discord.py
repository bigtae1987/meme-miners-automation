"""Post daily TAO earnings to a Discord webhook.

This script:
- Fetches TAO income for one or more coldkeys from the Taostats accounting API
- Aggregates earnings over a lookback window (in days)
- Posts a summary message to a Discord webhook

It is designed to run from GitHub Actions on a schedule.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List

# --- Environment configuration ---

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TAOSTATS_API_KEY = os.environ.get("TAOSTATS_API_KEY")

# Default to the same base used in the Taostats notebook examples
TAOSTATS_BASE_URL = os.environ.get("TAOSTATS_BASE_URL", "https://api.taostats.io/api")

# Comma-separated list of coldkeys
MINER_ADDRESSES = [
    addr.strip()
    for addr in os.environ.get("MINER_ADDRESSES", "").split(",")
    if addr.strip()
]

# Number of days to look back (e.g., 1 = "yesterday to today")
LOOKBACK_DAYS = int(os.environ.get("TAO_LOOKBACK_DAYS", "1"))

# Network name used in the accounting API (finney / nakamoto / kusanagi)
TAO_NETWORK = os.environ.get("TAO_NETWORK", "finney")


@dataclass
class MinerEarning:
    coldkey: str
    amount_tao: float


class DailyTaoReporter:
    def __init__(self) -> None:
        if not DISCORD_WEBHOOK_URL:
            raise RuntimeError("DISCORD_WEBHOOK_URL environment variable is required")
        if not TAOSTATS_API_KEY:
            raise RuntimeError("TAOSTATS_API_KEY environment variable is required")
        if not MINER_ADDRESSES:
            raise RuntimeError("MINER_ADDRESSES environment variable is required")

    # -------- Taostats API helpers --------

    def _headers(self) -> dict[str, str]:
        # Match the notebook style:
        # headers = {"accept": "application/json", "Authorization": api_key}
        return {
            "accept": "application/json",
            "Authorization": TAOSTATS_API_KEY,
        }

    def _endpoint(self) -> str:
        # Accounting endpoint from the notebook:
        # https://api.taostats.io/api/accounting/v1
        return f"{TAOSTATS_BASE_URL.rstrip('/')}/accounting/v1"

    def _date_range(self) -> tuple[str, str, date, date]:
        """Return (date_start_str, date_end_str, start_date, end_date)."""
        today_utc = datetime.now(timezone.utc).date()
        end_date = today_utc
        start_date = today_utc - timedelta(days=LOOKBACK_DAYS)

        return (
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            start_date,
            end_date,
        )

    def fetch_earnings(self) -> List[MinerEarning]:
        date_start_str, date_end_str, _, _ = self._date_range()

        earnings: List[MinerEarning] = []

        for coldkey in MINER_ADDRESSES:
            params = urllib.parse.urlencode(
                {
                    "network": TAO_NETWORK,
                    "date_start": date_start_str,
                    "date_end": date_end_str,
                    "coldkey": coldkey,
                    "page": 1,
                }
            )
            url = f"{self._endpoint()}?{params}"
            request = urllib.request.Request(url, headers=self._headers())

            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"Failed to fetch earnings for {coldkey}: {exc}") from exc

            # Notebook shape:
            # resJson['data'][0]['income'] and ['neuron_registration_cost'] in 1e9 units
            data = payload.get("data") or []
            if not data:
                # No entries for this coldkey in the date range
                continue

            record = data[0]
            income_raw = record.get("income")
            if income_raw is None:
                continue

            # Convert from 1e9 planck-like units to TAO
            try:
                income_tao = float(income_raw) / 1e9
            except (TypeError, ValueError):
                continue

            earnings.append(MinerEarning(coldkey=coldkey, amount_tao=income_tao))

        return earnings

    # -------- Discord helpers --------

    def build_message(self, earnings: List[MinerEarning]) -> str:
        date_start_str, date_end_str, start_date, end_date = self._date_range()

        if LOOKBACK_DAYS == 1:
            header = f"📊 Daily TAO Earnings — {end_date.isoformat()}"
        else:
            header = f"📊 TAO Earnings — {date_start_str} → {date_end_str}"

        if not earnings:
            return (
                f"{header}\n"
                f"Network: **{TAO_NETWORK}**\n"
                "No earnings data available for the configured coldkeys in this period."
            )

        lines = [
            header,
            f"Network: **{TAO_NETWORK}**",
            "",
        ]

        total = 0.0
        for entry in earnings:
            total += entry.amount_tao
            lines.append(f"• `{entry.coldkey}`: **{entry.amount_tao:.6f} TAO**")

        lines.append("")
        lines.append(f"**Total:** {total:.6f} TAO across {len(earnings)} coldkey(s)")

        return "\n".join(lines)

    def post_to_discord(self, content: str) -> None:
        payload = json.dumps({"content": content}).encode("utf-8")
        request = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.getcode()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Failed to send Discord message: {exc}") from exc

        print(f"✅ Message sent to Discord (status {status})")

    # -------- Main run --------

    def run(self) -> int:
        try:
            earnings = self.fetch_earnings()
            message = self.build_message(earnings)
        except Exception as exc:  # noqa: BLE001
            message = (
                "⚠️ Daily TAO Earnings — data unavailable\n"
                f"Reason: {exc}"
            )

        try:
            self.post_to_discord(message)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to send Discord message: {exc}", file=sys.stderr)
            return 1

        return 0


def main() -> None:
    sys.exit(DailyTaoReporter().run())


if __name__ == "__main__":
    main()
