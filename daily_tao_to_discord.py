 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/scripts/daily_tao_to_discord.py b/scripts/daily_tao_to_discord.py
new file mode 100644
index 0000000000000000000000000000000000000000..b0b817e7cb7ddcd53a0f811c50fb3315e7f76338
--- /dev/null
+++ b/scripts/daily_tao_to_discord.py
@@ -0,0 +1,148 @@
+"""Post daily TAO earnings to a Discord webhook.
+
+The script attempts to fetch miner earnings from a Taostats API-compatible
+endpoint and then posts a summary to Discord. It is designed to run from
+GitHub Actions and can fall back to sending a status update if the API is
+unavailable.
+"""
+from __future__ import annotations
+
+import json
+import os
+import sys
+import urllib.error
+import urllib.parse
+import urllib.request
+from dataclasses import dataclass
+from datetime import datetime, timezone
+from typing import Iterable, List, Mapping
+
+DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
+TAOSTATS_API_KEY = os.environ.get("TAOSTATS_API_KEY")
+TAOSTATS_BASE_URL = os.environ.get("TAOSTATS_BASE_URL", "https://taostats.io/api/v1")
+MINER_ADDRESSES = [
+    addr.strip()
+    for addr in os.environ.get("MINER_ADDRESSES", "").split(",")
+    if addr.strip()
+]
+LOOKBACK_DAYS = int(os.environ.get("TAO_LOOKBACK_DAYS", "1"))
+
+
+@dataclass
+class MinerEarning:
+    address: str
+    amount: float
+
+
+class DailyTaoReporter:
+    def __init__(self) -> None:
+        if not DISCORD_WEBHOOK_URL:
+            raise RuntimeError("DISCORD_WEBHOOK_URL environment variable is required")
+
+    def _headers(self) -> Mapping[str, str]:
+        headers = {"Accept": "application/json"}
+        if TAOSTATS_API_KEY:
+            headers["Authorization"] = f"Bearer {TAOSTATS_API_KEY}"
+        return headers
+
+    def _endpoint(self) -> str:
+        return f"{TAOSTATS_BASE_URL.rstrip('/')}/miners/earnings"
+
+    def fetch_earnings(self) -> List[MinerEarning]:
+        if not MINER_ADDRESSES:
+            raise RuntimeError("No miner addresses provided via MINER_ADDRESSES")
+
+        params = urllib.parse.urlencode({"addresses": ",".join(MINER_ADDRESSES), "days": LOOKBACK_DAYS})
+        url = f"{self._endpoint()}?{params}"
+
+        request = urllib.request.Request(url, headers=self._headers())
+        try:
+            with urllib.request.urlopen(request, timeout=30) as response:
+                payload = json.load(response)
+        except urllib.error.HTTPError as exc:
+            raise RuntimeError(f"Failed to fetch earnings: {exc}") from exc
+
+        earnings_data = payload.get("earnings", payload)
+
+        earnings: List[MinerEarning] = []
+        for record in self._to_iterable(earnings_data):
+            address = record.get("address") or record.get("miner") or record.get("uid")
+            amount = self._extract_amount(record)
+            if address is None or amount is None:
+                continue
+            earnings.append(MinerEarning(address=str(address), amount=float(amount)))
+        return earnings
+
+    def _extract_amount(self, record: Mapping[str, object]) -> float | None:
+        """Extract an amount value from several possible keys."""
+        for key in ("amount", "tao", "total", "total_tao", "value"):
+            if key in record and record[key] is not None:
+                try:
+                    return float(record[key])
+                except (TypeError, ValueError):
+                    return None
+        return None
+
+    def _to_iterable(self, data: object) -> Iterable[Mapping[str, object]]:
+        if isinstance(data, list):
+            return data
+        if isinstance(data, dict):
+            return data.values()
+        return []
+
+    def build_message(self, earnings: List[MinerEarning]) -> str:
+        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
+        if not earnings:
+            return (
+                f"📊 Daily TAO Earnings — {today}\n"
+                "No earnings data available for the configured miners."
+            )
+
+        lines = [f"📊 Daily TAO Earnings — {today}"]
+        total = 0.0
+        for entry in earnings:
+            total += entry.amount
+            lines.append(f"• {entry.address}: {entry.amount:.4f} TAO")
+        lines.append(f"Total: {total:.4f} TAO across {len(earnings)} miner(s)")
+        return "\n".join(lines)
+
+    def post_to_discord(self, content: str) -> None:
+        payload = json.dumps({"content": content}).encode("utf-8")
+        request = urllib.request.Request(
+            DISCORD_WEBHOOK_URL,
+            data=payload,
+            headers={"Content-Type": "application/json"},
+            method="POST",
+        )
+
+        try:
+            with urllib.request.urlopen(request, timeout=30) as response:
+                status = response.getcode()
+        except urllib.error.HTTPError as exc:
+            raise RuntimeError(f"Failed to send Discord message: {exc}") from exc
+
+        print(f"✅ Message sent to Discord (status {status})")
+
+    def run(self) -> int:
+        try:
+            earnings = self.fetch_earnings()
+            message = self.build_message(earnings)
+        except Exception as exc:  # pylint: disable=broad-exception-caught
+            message = (
+                "⚠️ Daily TAO Earnings — data unavailable\n"
+                f"Reason: {exc}"
+            )
+        try:
+            self.post_to_discord(message)
+        except Exception as exc:  # pylint: disable=broad-exception-caught
+            print(f"Failed to send Discord message: {exc}", file=sys.stderr)
+            return 1
+        return 0
+
+
+def main() -> None:
+    sys.exit(DailyTaoReporter().run())
+
+
+if __name__ == "__main__":
+    main()
 
EOF
)
