# utils.py
from datetime import datetime
from config import SCHEDULE_SHIFT_MIN, SCHEDULE_WINDOW_MIN


def is_time_to_send(target_hour, target_minute, now=None):
    """
    Пора ли отправлять?
    True, если now попадает в окно
    [target - SHIFT, target - SHIFT + WINDOW).
    """
    if now is None:
        now = datetime.now()

    now_min = now.hour * 60 + now.minute
    target_min = target_hour * 60 + target_minute - SCHEDULE_SHIFT_MIN
    delta = now_min - target_min
    return 0 <= delta < SCHEDULE_WINDOW_MIN