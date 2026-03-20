from datetime import date, timedelta


def nearest_friday(from_date: date | None = None) -> date:
    """
    Return the nearest upcoming Friday.
    - If today is Friday, returns today.
    - Otherwise returns the next Friday.
    """
    d = from_date or date.today()

    # weekday(): Monday=0 ... Friday=4
    days_ahead = (4 - d.weekday()) % 7

    return d + timedelta(days=days_ahead)