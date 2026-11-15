"""Turn a Chinese schedule transcript into a draft for the user to review."""

import re
import unicodedata
from datetime import date, datetime, time, timedelta


_DIGITS = "零〇○一二两兩三四五六七八九"
_VALUES = dict(zip(_DIGITS, (0, 0, 0, 1, 2, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
_NUM = rf"[0-9{_DIGITS}十]+"
_DAYPART = r"凌晨|清晨|早上|早晨|上午|中午|下午|午后|傍晚|晚上|夜间|夜里"
_PM = {"下午", "午后", "傍晚", "晚上", "夜间", "夜里"}
_LATE = {"晚上", "夜间", "夜里"}
_RELATIVE = {"前天": -2, "昨天": -1, "今天": 0, "今日": 0, "明天": 1,
             "明日": 1, "后天": 2, "大后天": 3}
_RELATIVE_YEAR = {"去年": -1, "今年": 0, "明年": 1, "后年": 2, "後年": 2}
_DATE_ALIASES = {
    "今早": "今天早上", "今晚": "今天晚上", "明早": "明天早上",
    "明晚": "明天晚上", "昨晚": "昨天晚上", "後天": "后天",
}
_WEEKDAY = {ch: i for i, ch in enumerate("一二三四五六日")}
_WEEKDAY.update({"天": 6, **{str(i + 1): i for i in range(7)}})

_DATE = re.compile(
    rf"(?P<iso>(?<!\d)\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}(?!\d))|"
    r"(?<![a-zA-Z0-9])(?P<short_month>\d{1,2})[./](?P<short_day>\d{1,2})\s*(?:日|号|號)|"
    rf"(?:(?P<relative_year>去年|今年|明年|后年|後年)\s*|(?P<year>{_NUM})\s*年\s*)?"
    rf"(?P<month>{_NUM})\s*月\s*(?P<day>{_NUM})\s*(?:日|号|號)|"
    rf"(?P<relative>大后天|前天|昨天|今天|今日|明天|明日|后天)|"
    rf"(?P<offset>{_NUM})\s*天\s*(?P<direction>后|後|前)|"
    r"(?P<week>下下|下|上上|上|本|这|這)?\s*(?:个|個)?\s*(?:周|週|星期|礼拜|禮拜)\s*(?P<weekday>[一二三四五六日天1-7])"
)
_CLOCK_TEXT = (
    rf"(?:{_DAYPART})?\s*{_NUM}\s*"
    rf"(?::\s*[0-9]{{2}}(?!\d)|[点點时時](?:\s*(?:半|一刻|三刻|{_NUM}\s*分?))?[钟鐘]?)"
)
_CLOCK = re.compile(
    rf"(?<![a-zA-Z0-9])(?P<part>{_DAYPART})?\s*(?P<hour>{_NUM})\s*"
    rf"(?::\s*(?P<digits>[0-9]{{2}})(?!\d)|[点點时時](?:\s*(?P<spoken>半|一刻|三刻|{_NUM})\s*分?)?[钟鐘]?)"
)
_RANGE = re.compile(
    rf"(?P<start>{_CLOCK_TEXT})\s*(?:到|至|[-–—~～])\s*"
    rf"(?P<end>{_CLOCK_TEXT}|(?:{_DAYPART})?\s*{_NUM}(?![0-9{_DIGITS}十]))"
)
_SHORT_RANGE = re.compile(
    rf"(?P<part>{_DAYPART})?\s*(?P<hour>{_NUM})\s*(?:到|至|[-–—~～])\s*(?P<end>{_CLOCK_TEXT})"
)
_BARE_CLOCK = re.compile(rf"(?P<part>{_DAYPART})?\s*(?P<hour>{_NUM})\s*$")
_PREFIX = re.compile(
    r"^\s*(?:(?:麻烦|麻煩|请|請)\s*)?(?:帮我|幫我)?\s*"
    r"(?:添加|新增|加上|加入|加|记一下|記一下|记下|記下|安排|提醒我)\s*"
    r"(?:一个|一個|一条|一條|个|個)?\s*(?:(?:日程|事项|事項|提醒|待办|待辦)\s*)?[:：,，\s]*"
)
_PUNCTUATION = " ,，。.;；、:：!！?？\t\r\n"
_ACTION = (
    r"参加|參加|出席|开会|開會|开组会|開組會|组会|組會|见面|見面|考试|考試|上课|上課|上班|"
    r"讨论|討論|吃饭|吃飯|聚餐|开题|開題|面试|面試|交作业|交作業|复习|複習|写|寫|跑步|洗牙|看病|处理|處理"
)
_EXPLICIT_PLACE = re.compile(r"(?:地点|地點|位置)\s*(?:在|是|:)?\s*(?P<place>[^,，。；;!?！？\n]+)")
_IN_PLACE = re.compile(
    rf"(?<![现現])在(?![线線场場读讀])\s*(?P<place>[^,，。；;!?！？\n]+?)"
    rf"\s*(?={_ACTION}|[,，。；;!?！？\n]|$)"
)
_GO_PLACE = re.compile(rf"去\s*(?P<place>[^,，。；;!?！？\n]+?)\s*(?={_ACTION})")
_NOTES = re.compile(r"(?:^|[,，。；;\s])备注\s*:?\s*(.+)$")
_ACTIVITY = re.compile(
    r"报名|報名|讲座|講座|研讨会|研討會|工作坊|论坛|論壇|校招|比赛|比賽|音乐会|音樂會|"
    r"展览|展覽|面试|面試|联谊|聯誼|活动|活動|组会|組會"
)
_DEADLINE = re.compile(r"截止|最[晚迟遲]|最[后後]期限|(?<![a-z])(?:ddl|deadline)(?![a-z])", re.I)
_ASSIGNMENT = re.compile(
    r"作业|作業|考试|考試|测验|測驗|答辩|答辯|期中|期末|互评|互評|课程|課程|上课|上課|交报告|交報告|交论文|交論文|"
    r"(?<![a-z0-9])(?:quiz|ddl|deadline|assignment)(?![a-z])|(?<![a-z0-9])(?:COMP|AF|SD)\s*\d{4}(?!\d)",
    re.IGNORECASE,
)


def _number(value):
    if "十" in value:
        if value.count("十") > 1:
            raise ValueError("Invalid number")
        tens, ones = value.split("十", 1)
        return 10 * (_number(tens) if tens else 1) + (_number(ones) if ones else 0)
    return int("".join(str(_VALUES.get(char, char)) for char in value))


def _calendar_date(match, base):
    if match["iso"]:
        year, month, day = map(int, re.split("[-/]", match["iso"]))
        return date(year, month, day)
    if match["short_month"]:
        return date(base.year, int(match["short_month"]), int(match["short_day"]))
    if match["month"]:
        month = _number(match["month"])
        day = _number(match["day"])
        year = base.year
        if match["year"]:
            year = _number(match["year"])
        elif match["relative_year"]:
            year += _RELATIVE_YEAR[match["relative_year"]]
        return date(year, month, day)
    if match["relative"]:
        return base + timedelta(days=_RELATIVE[match["relative"]])
    if match["offset"]:
        sign = -1 if match["direction"] == "前" else 1
        return base + timedelta(days=sign * _number(match["offset"]))

    weekday = _WEEKDAY[match["weekday"]]
    week = match["week"]
    if week is None:
        return base + timedelta(days=(weekday - base.weekday()) % 7)
    week_offset = {"下下": 2, "下": 1, "上上": -2, "上": -1}.get(week, 0)
    return base + timedelta(days=week_offset * 7 + weekday - base.weekday())


def _clock(match, inherited_part=""):
    hour = _number(match["hour"])
    fields = match.groupdict()
    part = fields.get("part") or inherited_part
    spoken = fields.get("spoken")
    minute = 0
    if fields.get("digits"):
        minute = int(fields["digits"])
    elif spoken:
        minute = {"半": 30, "一刻": 15, "三刻": 45}.get(spoken)
        if minute is None:
            minute = _number(spoken)
    if hour == 24 and minute == 0:
        return time(0), 1
    if hour == 12 and part in _LATE:
        return time(0, minute), 1
    if hour == 12 and part == "凌晨":
        hour = 0
    if 1 <= hour < 12 and (part in _PM or part == "中午" and hour <= 2):
        hour += 12
    return time(hour, minute), 0


def _compact(value):
    return re.sub(r"\s+", " ", value).strip(_PUNCTUATION)


def _remove(value, match):
    return value[:match.start()] + " " + value[match.end():]


def _remove_clock(value, match):
    before = re.sub(r"(?:从|從|于|於|(?<![现現存])在)\s*$", "", value[:match.start()])
    return before + " " + value[match.end():]


def _extract_times(value, event_date, warnings):
    time_range = _RANGE.search(value) or _SHORT_RANGE.search(value)
    if time_range:
        groups = time_range.groupdict()
        first = _CLOCK.fullmatch(groups["start"].strip()) if "start" in groups else time_range
        second_value = groups["end"].strip()
        second = _CLOCK.fullmatch(second_value) or _BARE_CLOCK.fullmatch(second_value)
        original = _remove_clock(value, time_range)
    else:
        first = _CLOCK.search(value)
        second = None
        original = _remove_clock(value, first) if first else value

    if not first:
        part = re.search(_DAYPART, value)
        if part and event_date:
            warnings.append("识别到了时段，具体时间待填写。")
            original = _remove(value, part)
        return original, None, None
    try:
        start_clock, offset = _clock(first)
        start = datetime.combine(event_date + timedelta(days=offset), start_clock) if event_date else None
    except (OverflowError, ValueError):
        warnings.append("开始时间无效，请核对。")
        return original, None, None
    if start is None:
        return original, None, None
    if second is None:
        return original, start, None
    try:
        part = first["part"] or ""
        end_clock, end_offset = _clock(second, part)
        end = datetime.combine(event_date + timedelta(days=end_offset), end_clock)
        if end <= start and (second["part"] == "凌晨" or (
            part in _LATE and second["part"] is None and _number(second["hour"]) <= 5
        )):
            end_clock, _ = _clock(second, "凌晨")
            end = datetime.combine(start.date() + timedelta(days=1), end_clock)
            warnings.append("结束时间按次日理解，请核对。")
        if end <= start:
            warnings.append("结束时间应晚于开始时间，请核对。")
            end = None
    except (OverflowError, ValueError):
        warnings.append("结束时间无效，请核对。")
        end = None
    return original, start, end


def parse_schedule(text: str, base_date: datetime) -> dict:
    """Parse a transcript in the caller's local timezone without creating an event."""
    value = unicodedata.normalize("NFKC", text).strip()
    for alias, expanded in _DATE_ALIASES.items():
        value = value.replace(alias, expanded)
    warnings = []
    date_match = _DATE.search(value)
    event_date = None
    if date_match:
        try:
            event_date = _calendar_date(date_match, base_date.date())
        except (OverflowError, ValueError):
            warnings.append("日期无效，请核对。")
        value = _remove(value, date_match)
        if re.search(r"\bT\s*\d{1,2}:", value):
            value = re.sub(r"\bT(?=\s*\d{1,2}:)", "", value, count=1)
        if _DATE.search(value):
            warnings.append("识别到多个日期，草稿采用第一个日期，请核对。")
    else:
        warnings.append("没有识别到日期，请填写日期。")

    notes_match = _NOTES.search(value)
    notes = _compact(notes_match[1]) if notes_match else ""
    if notes_match:
        value = value[:notes_match.start()]
    value, start, end = _extract_times(value, event_date, warnings)
    location = ""
    place_match = _EXPLICIT_PLACE.search(value) or _IN_PLACE.search(value) or _GO_PLACE.search(value)
    if place_match:
        title_without_place = _compact(_PREFIX.sub("", _remove(value, place_match), count=1))
        if title_without_place:
            location = _compact(place_match["place"])
            value = _remove(value, place_match)
    title = _compact(_PREFIX.sub("", value, count=1))
    category = "life"
    if re.search(r"报名截止|報名截止", title):
        category = "activity"
    elif _ASSIGNMENT.search(title):
        category = "assignment"
    elif _ACTIVITY.search(title):
        category = "activity"
    if not title:
        warnings.append("没有识别到日程名称，请填写标题。")
    kind = "deadline" if _DEADLINE.search(title) else "event"
    if kind == "deadline" and end:
        warnings.append("识别到截止事项和时间段，请核对具体截止时间。")
        end = None

    date_only = event_date.isoformat() if event_date else ""
    return {
        "draft": {
            "title": title,
            "category": category,
            "kind": kind,
            "start": start.isoformat(timespec="minutes") if start else date_only,
            "end": end.isoformat(timespec="minutes") if end else None,
            "all_day": start is None and event_date is not None,
            "location": location,
            "notes": notes,
        },
        "warnings": warnings,
    }
