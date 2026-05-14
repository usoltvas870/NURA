import re
from datetime import datetime

DATE_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def validate_date(date_str: str) -> bool:
    if not DATE_PATTERN.match(date_str):
        return False
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
        return True
    except ValueError:
        return False
