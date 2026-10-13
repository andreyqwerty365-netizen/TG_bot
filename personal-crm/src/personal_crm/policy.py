from datetime import timedelta
from zoneinfo import ZoneInfo


def notification_allowed(kind, now, timezone, events, limit=2):
    """Events include successful, uncertain and reserved deliveries; errors consume nothing."""
    if kind == "exact":
        return True
    if not timezone:
        return False
    zone = ZoneInfo(timezone)
    day = now.astimezone(zone).date()
    if kind == "digest":
        return not any(k == "digest" and t.astimezone(zone).date() == day for k, t in events)
    initiatives = [t for k, t in events if k in ("initiative", "repeat")]
    return (
        sum(t.astimezone(zone).date() == day for t in initiatives) < limit
        and all(now - t >= timedelta(hours=4) for t in initiatives)
    )
