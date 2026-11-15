"""Extract explicitly scheduled items from the existing Gmail diary Markdown."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


SHANGHAI = timezone(timedelta(hours=8))
DAY = r"(?:[0-3]?\d)"
MONTH = r"(?:[01]?\d)"
DASH = r"[–—－~～-]"
DATE = re.compile(
    rf"(?<!\d)(?:(?P<iso>20\d{{2}}-{MONTH}-{DAY})(?!\d)|"
    rf"(?:(?P<year>20\d{{2}})\s*年\s*)?(?P<month>{MONTH})\s*月\s*"
    rf"(?P<day>{DAY})(?:\s*{DASH}\s*(?P<through>{DAY}))?\s*日"
    rf"(?:\s*(?:及|和|、|与)\s*(?P<also>{DAY})\s*日)?|"
    rf"(?P<month_day>{DAY})\s*日(?![程志])|(?P<relative>前天|昨天|昨日|今天|今日|明天|明日|后天))"
)
CLOCK = r"(?:[01]?\d|2[0-3]):[0-5]\d"
TIME = re.compile(rf"(?<![\d:])({CLOCK})(?![\d:]|\s*秒)(?:\s*(?:{DASH}|至|到)\s*({CLOCK})(?![\d:]))?")
OFFSET = re.compile(r"\b(?:UTC|GMT)\s*([+−-])\s*(\d{1,2})(?::([0-5]\d))?", re.I)
LINK = re.compile(r"\[([^\]\n]+)\]\(([^\s)]+)\)")
GMAIL_MESSAGE_URL = re.compile(
    r"https://mail\.google\.com/mail/(?:u/(?:\d+/?)?)?(?:\?[^#\s]*)?"
    r"#(?:all|inbox|sent|starred|important|snoozed|drafts|spam|trash|(?:search|label)/[^/#\s]+)"
    r"/[a-z0-9_-]+",
    re.I,
)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BULLET = re.compile(r"^(\s*)[-*]\s+(?:\[([ xX])\]\s*)?(.+)")
DEADLINE = re.compile(r"截止|到期|最后期限|之前|不迟于|限期|缴款日|缴费日|还款日|交费日|报名(?:于|至)|(?:^|\s)前\s*(?:提交|缴费|报名|登记|投稿|申请|交费|答题|注册|退出)|(?:^|\s)交(?:计划|成品|材料|报告|作业)|\bDDL\b", re.I)
LIFE = re.compile(r"截止|到期|(?:缴[款费]|还款|续费|交费)(?:日|日期|期限|前|截止)|生效|停水|停电|暂停|暂停开放|闭馆|关闭|维护|搬迁|停运|预约|停课")
RECEIPT = re.compile(r"原收件|回溯|原发|交易日期|账单生成|用户于|(?:收到|发出|发送|到达|收件)(?:日|时间|于|\b)|邮件(?:于|日期)|邮件覆盖")
RESCHEDULED = re.compile(r"延期|延后|延长|更改|改至|改到|改为|调整|变更|推迟|更新为|新(?:的)?截止|最新截止")
NEGATED = re.compile(r"(?:不再|未改|未更改|未列|未写|未披露|未注明|未明确|不据此|待核对|日期待确认)[^。；，,]{0,16}$")
INVITED = re.compile(r"已报名|已获录取|已确认(?:报名|登记|参加)|(?:报名|登记|注册|录取)(?:成功|确认回执)|个人(?:入场|报名|录取)确认")
NOT_INVITED = re.compile(r"(?:未|没有|尚无|无|待核对|另发|另收|并非|不代表)[^，。；]{0,10}(?:已报名|成功|确认|录取)|(?:报名|录取|个人登记)状态(?:待|未|未知)")
QUIZ = re.compile(r"\bQuiz\s*#?\s*(\d+)\b", re.I)
ASSIGNMENT = re.compile(r"\b([A-Z]{2,}\s*\d{4})\s*(?:Assignment\s*|A\s*)(\d+)\b", re.I)
GROUP_PROJECT = re.compile(r"展示(?:结束)?后(?:的)?(?:小组)?项目", re.I)
FIRST_SUBMISSION = re.compile(r"\bAF\s*5640\b[^。；]{0,55}(?:Group Project|DATS)", re.I)
COURSE_ACTION = re.compile(r"考试|答辩|答辯|展示|讲演|講演|测验|測驗|演示|面试|课表")
DIVIDE = re.compile(r"[。；;！!?！？]")
LOCATION_MARK = re.compile(r"(?:地点|会场|地点为|地點|現場|场地|线下地点|Venue)\s*[:：]\s*([^。；，,]+)", re.I)
VENUE = re.compile(r"Zoom|Teams|线上|線上|线下|線下|理大|港大|校区|教室|剧院|劇院|会议室|陈列室|大[厦廈]|酒店|楼|樓|[A-Z]{1,4}\s*\d{2,4}|Hall|Tower|Room|Campus|Centre|Center|礼堂|場館|柜台|平[台臺]", re.I)
IGNORE_NAME = re.compile(r"^(?:本轮|本日|今日原列可选活动|早报|午报|晚报|补记状态|无新增|原记录与提交状态保留|近期(?:任务|课程事项)|最近有效待办|尚未归类|明确待办|原记录保留|考表核对|核对并保存个人期末考试时间表|昨日收件的|接下来三项|时间安排|明天安排提示)")
CATEGORIES = {"作业任务": "assignment", "活动": "activity", "生活": "life", "手动补充": "manual"}


@dataclass
class Record:
    day: date
    category: str
    title: str
    content: str
    links: list[tuple[str, str]]
    completed: bool = False
    table: bool = False
    manual: bool = False


@dataclass
class DateMatch:
    match: re.Match[str]
    days: list[date]


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", LINK.sub("", value).replace("**", "").replace("`", "")).strip()


def record_title(value: str, table: bool = False) -> str:
    bold = re.match(r"\*\*(.+?)\*\*", value)
    first = bold.group(1) if bold else (value if table else re.split(r"[。；：｜]", value, maxsplit=1)[0])
    first = re.sub(r"[，,]\s*\d{1,2}:\d{2}:\d{2}\s*$", "", first)
    first = clean(first).strip(" ·：:。")
    return first[:120]


def records(markdown: str) -> list[Record]:
    day = None
    category = None
    title = ""
    completed = False
    last = None
    manual_category = "assignment"
    in_comment = False
    result = []
    for line in markdown.splitlines():
        line = line.lstrip("\ufeff")
        if "<!--" in line or in_comment:
            in_comment = "-->" not in line
            continue
        heading = HEADING.match(line)
        if heading:
            level, label = heading.groups()
            if level == "#":
                day = parse_day(label)
                category = None
            elif level == "##":
                category = CATEGORIES.get(label.strip())
                manual_category = "assignment"
            elif level == "###" and category == "manual":
                manual_category = CATEGORIES.get(label.strip(), "assignment")
            title, last = "", None
            continue
        if day is None or category is None or not line.strip():
            continue
        actual_category = manual_category if category == "manual" else category
        if line.startswith("|"):
            fields = [field.strip() for field in line.strip().strip("|").split("|")]
            if len(fields) < 3 or re.fullmatch(r"[-: ]+", fields[0]) or fields[0] in {
                "活动", "事项", "通知", "任务", "生活事项", "项目", "活动／机会", "名称", "内容"
            }:
                continue
            title = record_title(fields[0], table=True)
            result.append(Record(day, actual_category, title, "；".join(fields), LINK.findall(line), table=True, manual=category == "manual"))
            last = None
            continue
        bullet = BULLET.match(line)
        if bullet:
            indent, check, content = bullet.groups()
            if not indent or not title:
                title, completed = record_title(content), check in {"x", "X"}
            name = title if indent and title else record_title(content)
            last = Record(day, actual_category, name, content, LINK.findall(content), completed, manual=category == "manual")
            result.append(last)
        elif last and line[:1].isspace():
            last.content += " " + line.strip()
            last.links.extend(LINK.findall(line))
        elif line.startswith("**"):
            name = record_title(line)
            result.append(Record(day, actual_category, name, line, LINK.findall(line), manual=category == "manual"))
            last = None
    return result


def parse_day(value: str) -> date | None:
    try:
        year, month, day = (int(part) for part in value.split("-"))
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def dates(value: str, source_day: date) -> list[DateMatch]:
    output = []
    previous = None
    relative = {"前天": -2, "昨天": -1, "昨日": -1, "今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2}
    for match in DATE.finditer(value):
        parts = match.groupdict()
        found = []
        try:
            if parts["iso"]:
                found = [parse_day(parts["iso"])]
            elif parts["relative"]:
                found = [source_day + timedelta(days=relative[parts["relative"]])]
            elif parts["month"]:
                month = int(parts["month"])
                year = int(parts["year"]) if parts["year"] else source_day.year
                if parts["year"] is None:
                    if source_day.month - month > 6:
                        year += 1
                    elif month - source_day.month > 6:
                        year -= 1
                start = int(parts["day"])
                numbers = [start]
                if parts["also"]:
                    numbers.append(int(parts["also"]))
                elif parts["through"]:
                    through = int(parts["through"])
                    if start > through or through - start > 31:
                        continue
                    numbers = range(start, through + 1)
                found = [date(year, month, day) for day in numbers]
            elif previous and parts["month_day"]:
                found = [previous.replace(day=int(parts["month_day"]))]
        except ValueError:
            continue
        if found and found[0] is not None:
            previous = found[-1]
            output.append(DateMatch(match, found))
    return output


def identity(value: str, context: str = "") -> tuple[str, str] | None:
    assignment = ASSIGNMENT.search(value)
    quiz = QUIZ.search(value)
    project = GROUP_PROJECT.search(value)
    first_submission = FIRST_SUBMISSION.search(value)
    if assignment:
        course, number = assignment.groups()
        course = course.replace(" ", "").upper()
        return f"{course.lower()}-a{number}", f"{course} A{number}"
    if quiz:
        number = quiz.group(1)
        return f"quiz-{number}", f"Quiz {number}"
    if project and re.search(r"\bAF\s*5640\b|Machine Share", f"{value} {context}", re.I):
        return "af5640-project", "AF5640 小组项目"
    if first_submission:
        return "af5640-dats-submission", "AF5640 双入口提交"
    if re.search(r"UX[^。；]{0,25}(?:互评|Peer Evaluation)", value, re.I):
        return "ux-peer-review", "UX 小组互评"
    return None


def tidy_title(title: str, record: Record) -> str:
    title = re.sub(r"^(?:已报名|报名成功|已确认|后续|延期|确认)\s*[:：]\s*", "", title)
    title = re.sub(r"[（(](?:次日|当日|手动|回溯)[^）)]*(?:补记|更新)[）)]", "", title)
    matched = DATE.search(title)
    if matched and matched.start() > 1:
        prefix = title[:matched.start()].strip(" （(:：")
        if len(prefix) > 2 and not re.search(r"\d{4} 届$", prefix):
            title = prefix
    title = re.sub(r"(?:[（(][^）)]*(?:提醒|延期|更新)[^）)]*[）)])$|(?:最后提醒|重复提醒(?:合并)?|提醒邮件|新提醒|提醒)$", "", title)
    title = re.sub(r"(?:原列|仍为|延期至|改为|延期|更新|：|:)\s*$", "", title)
    title = title.strip(" ·—–，,：:；;。")
    return title or record.title


def date_context(value: str, start: int, end: int) -> tuple[str, str]:
    left = re.split(r"[，,。；;、]", value[:start])[-1].strip()
    right = re.split(r"[，,。；;、]", value[end:], maxsplit=1)[0].strip()
    return left, right


def known_event(title: str) -> tuple[str, str] | None:
    aliases = (
        (r"RISE.+(?:情境视频|Scenario Development Competition)", "rise-scenario", "RISE 情境视频比赛"),
        (r"COMPCERT.*(?:AI 视频比赛|AI Video Competition)", "compcert-ai-video", "COMPCERT AI 视频比赛"),
        (r"校长(?:与学生)?分享会", "president-student-sharing", "理大校长与学生分享会"),
        (r"PRI.+(?:光互连|Optical Interconnect)", "pri-optical-interconnect", "PRI 云及 AI 数据中心光互连讲座"),
        (r"RICRI.+(?:抗灾基础设施|Resilien)", "ricri-resilient-infrastructure", "RICRI 抗灾基础设施讲座"),
        (r"中国蓝图|The Chinese Blue Maps", "chinese-blue-maps", "中国蓝图讲座及圆桌"),
        (r"Mapping Islands in Early Modern Sinographic Asia|东亚早期近代岛屿地图", "mapping-islands", "RCCHC 东亚早期近代岛屿地图讲座"),
        (r"CUS.*(?:内地学习经验|学生分享)", "cus-sharing", "CUS 内地学习经验学生分享会"),
        (r"港韩数学金融工作坊", "hong-kong-korea-finance", "港韩数学金融工作坊"),
        (r"第一创业证券.*开放日", "first-capital-open-day", "第一创业证券「未来金融创想家」开放日"),
        (r"体育科学与技术研讨会", "sports-science-symposium", "体育科学与技术研讨会"),
        (r"XR\s*期中考试", "xr-midterm", "XR 期中考试"),
        (r"UX\s*答辩", "ux-defense", "UX 答辩"),
        (r"元宇宙经济", "metaverse-economics", "元宇宙经济"),
    )
    for pattern, key, name in aliases:
        if re.search(pattern, title, re.I):
            return key, name
    return None


def source_link(record: Record, kind: str, title: str) -> str:
    links = [(label, url) for label, url in record.links if re.match(r"https?://", url, re.I)]
    if kind == "deadline" and record.category == "assignment":
        assignment_links = [(label, url) for label, url in links if "/assignments/" in url]
        for label, url in assignment_links:
            if identity(label) and identity(label) == identity(title):
                return url
        if len(assignment_links) == 1 and (not QUIZ.search(title) or not ASSIGNMENT.search(record.content)):
            return assignment_links[0][1]
    gmail = [url for _, url in links if re.match(r"https://mail\.google\.com/mail/", url, re.I)]
    return gmail[-1] if gmail else (links[0][1] if links else "")


def original_mail_link(record: Record, title: str) -> str:
    links = [(label, url) for label, url in record.links if GMAIL_MESSAGE_URL.fullmatch(url)]
    urls = {url for _, url in links}
    if len(urls) <= 1:
        return next(iter(urls), "")

    name = text_key(re.sub(r"\s*·\s*(?:报名)?截止$", "", title))
    item = identity(title) or known_event(title)
    matches = set()
    for label, url in links:
        label_name = text_key(label)
        same_name = len(name) >= 4 and name in label_name
        if same_name or item and item == (identity(label) or known_event(label)):
            matches.add(url)
    return next(iter(matches)) if len(matches) == 1 else ""


def schedule_location(tail: str, segment: str) -> str:
    marker = LOCATION_MARK.search(segment)
    if marker:
        return marker.group(1).strip()
    tail = re.sub(r"^\s*(?:HKT|香港時間|香港时间|北京时间|CST|[（(]UTC[^）)]*[)）]|UTC\s*[+−-]\d{1,2})*\s*[，,、；;:：]\s*", "", tail, flags=re.I) if tail.strip() else tail
    tail = re.sub(r"^(?:HKT|香港時間|香港时间|北京时间|CST)\s*", "", tail.strip(), flags=re.I)
    first = re.split(r"[、，,。；;]|另设|另設", tail, maxsplit=1)[0].strip(" ,")
    if first.startswith(("（", "(")):
        first = first[1:].removesuffix("）").removesuffix(")")
    return first[:100] if VENUE.search(first) and len(first) <= 100 else ""


def normalize_time(day: date, hour: str, offset: re.Match[str] | None) -> datetime:
    result = datetime.fromisoformat(f"{day.isoformat()}T{hour.zfill(5)}")
    if offset:
        sign = 1 if offset[1] == "+" else -1
        difference = sign * timedelta(hours=int(offset[2]), minutes=int(offset[3] or 0))
        return result + (timedelta(hours=8) - difference)
    return result


def item_status(record: Record, kind: str) -> str:
    if record.completed:
        return "completed"
    if record.manual:
        return "planned"
    if kind == "notice":
        return "notice"
    if record.category == "activity" and kind != "notice":
        if INVITED.search(record.content) and not NOT_INVITED.search(record.content):
            return "confirmed"
        return "invitation"
    return "planned"


def choose_type(record: Record, segment: str, left: str, right: str, clock: re.Match[str] | None) -> str | None:
    local = f"{left} {right}"
    if RECEIPT.search(local) or re.search(r"^(?:收件|原发|发出|到达|发布|收到|签收|转入|公告|周报|答疑|邮件)(?:\b|[，,]|前|后)", right):
        return None
    if NEGATED.search(left) or re.search(r"(?:重合|冲突|替代原|取代原|旧截止|不再沿用|回溯补记)", left):
        return None
    if DEADLINE.search(local) or re.search(r"^前\s*(?:双入口)?(?:提交|缴费|报名|登记|投稿|申请|交费|答题|注册|退出)", right):
        return "deadline"
    if record.category == "activity" and RESCHEDULED.search(left) and re.search(r"比赛|競賽|竞赛|征集|招募|Competition", record.title, re.I):
        return "deadline"
    if record.category == "life":
        return "notice" if LIFE.search(f"{record.title} {segment}") else None
    if record.category == "assignment":
        if identity(segment) and (clock or RESCHEDULED.search(segment)) and not re.search(r"发布|已提交|回执|答疑", local):
            return "deadline"
        if COURSE_ACTION.search(record.title) and not re.search(r"发布时间|发布|提交|截止|成绩|答疑|考试期|温习|复习|时间表|补记", f"{local} {record.title}") and (clock or re.search(r"考试|答辩|评审|展示|安排|全天|日期|用户于", f"{local} {record.title}")):
            return "event"
        if record.manual or re.search(r"来源：用户于|手动添加|用户告知", record.content) and not IGNORE_NAME.search(record.title):
            return "event"
        return None
    if re.search(r"(?:早于|收到|曾于|发出|结果|签到|视频可|提交回执|活动后|名单|公布|展示成果|截止|报名|登记|收件|原发)", right) and not clock:
        return None
    if re.search(r"收件|日期待|未知|日期未|过去活动|比赛成绩|签到及视频", record.title):
        return None
    if re.search(r"累计服务区间|才开放申请|获.*机会|仅有机会获|结果发布|原日期|示例|首批名单|在线报名|结束报名|原报名|^补记", local):
        return None
    if clock or re.search(r"全天|举行|舉行|举办|舉辦|安排|邀请|演出|活动为|仍为|开展|连办|活动定于|日期沿用|日期为", local) or record.table and re.search(r"研讨|講座|讲座|Forum|Workshop|会|展|论坛|交流|比赛|参访|導覽|导览|Ceremony|宣讲", record.title, re.I):
        return "event"
    return None


def candidates(record: Record) -> list[tuple[dict, str, int]]:
    value = clean(record.content)
    if not value or record.category == "life" and re.match(r"(?:Google Play|Dropbox)\s*.*(?:条款|隐私政策)", record.title, re.I) and not re.search(r"必须|请在[^。]+前|[¥￥$]\s*\d|(?:缴费|取消|退订|迁移)截止", value):
        return []
    parsed_dates = dates(value, record.day)
    output = []
    for index, found in enumerate(parsed_dates):
        match = found.match
        previous = parsed_dates[index - 1].match if index else None
        following = parsed_dates[index + 1] if index + 1 < len(parsed_dates) else None
        if match["relative"] and following and following.match.start() - match.end() <= 3:
            continue
        if previous and re.fullmatch(r"[（(]?(?:至|到|-|–|—)\s*", value[previous.end():match.start()]) and found.days[0] == parsed_dates[index - 1].days[-1]:
            continue
        left, right = date_context(value, match.start(), match.end())
        if re.search(r"(?:来源[：:]\s*用户于|用户于|手动补记于|日期为原邮件|记录于|核对于|回溯于)\s*$", left) or re.match(r"^(?:课程公告补齐|实际查阅后更新|回溯补记|发布后更新)", right):
            continue
        segment_start = max((separator.end() for separator in DIVIDE.finditer(value, 0, match.start())), default=0)
        separator = DIVIDE.search(value, match.end())
        segment_end = separator.start() if separator else len(value)
        segment = value[segment_start:segment_end]
        time_end = min(segment_end, following.match.start()) if following else segment_end
        tail = value[match.end():time_end]
        time = TIME.search(tail)
        if time:
            before_clock = tail[:time.start()]
            before_clock = re.sub(r"^\s*(?:[(（][^）)\d]{1,10}[)）])?\s*(?:每天|当日|当天|时间为|於|于|从|自|每场|上午|下午|晚上)?\s*", "", before_clock)
            if before_clock and not re.fullmatch(r"(?:[\w／ ]{1,30}(?:考试|答辩|展示|宣讲|活动))?\s*[:：,，]?\s*", before_clock):
                time = None
        if match["relative"] and not time and not re.match(r"\s*(?:全天|截止|举行|暂停)", tail):
            continue
        if match["month_day"] and not time and not re.match(r"\s*(?:全天|截止|暂停|或之前|前)", tail):
            continue
        if not time and following and re.fullmatch(r"\s*(?:至|到|[-–—])\s*", tail):
            continue
        kind = choose_type(record, segment, left, right, time)
        if not kind:
            continue
        if previous and index and re.search(r"(?:原\s*|由原[^\d]{0,7})$", left) and RESCHEDULED.search(segment) and not re.search(r"延期后的|最新", left):
            continue
        if re.search(r"(?:\b\d{1,2}:\d{2}:\d{2}\b\s*(?:的)?(?:邮件|公告|通报|收到|到达|收件))|(?:^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:收件|到达|收到|发布))", right):
            continue
        if match.start() == segment_start and following and following.match.start() < segment_end and not time:
            if re.match(r"\s*(?:延期更新|周报补充|邮件|补记|通知|公告|答疑)", right):
                continue

        item_title = tidy_title(record.title, record)
        known = identity(left, value) or identity(segment, value) or (identity(record.title, value) if record.category == "assignment" else None)
        key = ""
        if known and kind == "deadline" and record.category == "assignment":
            key, item_title = known
        event_alias = known_event(item_title)
        if event_alias and (record.category == "activity" or kind == "event"):
            key, item_title = event_alias
        if key == "first-capital-open-day":
            if not time:
                continue
            if time[1] == "00:00" and re.search(r"24:00", value):
                kind = "deadline"
        if key == "sports-science-symposium" and not time:
            continue
        if kind == "event" and record.category == "assignment" and not time and not record.manual and not re.search(r"来源：用户于|日期为|全天", value):
            continue
        if "FCMS" in value and record.category == "life" and re.search(r"暂停|恢复|关闭", segment, re.I):
            if time and re.match(r"^\s*恢复", tail[time.end():]):
                key, item_title = "fcms-resume", "FCMS 柜台恢复服务"
            elif re.match(r"^\s*全天\s*暂停", tail):
                key, item_title = "fcms-service", "FCMS 柜台暂停开放"
            else:
                continue
        if not item_title or IGNORE_NAME.search(item_title) and not key:
            continue
        qualification = f"{left} {right}"
        has_registration = any(re.search(r"报名|登记|注册|申请", label) for label, _ in record.links)
        if kind == "deadline" and record.category == "activity" and (re.search(r"报名|登记|注册|申请|退出", qualification) or has_registration and not re.search(r"比赛|竞赛|作品|投稿|项目", item_title)):
            item_title += " · 报名截止"
        elif kind == "deadline" and record.category == "activity" and "截止" not in item_title:
            item_title += " · 截止"
        if kind == "event" and key in {"rise-scenario", "compcert-ai-video"}:
            if not time or not re.search(r"颁奖|音乐会", left):
                continue
            item_title += " · 颁奖音乐会"
        if kind == "event" and re.match(r"正式(?:歌剧)?演出", left):
            item_title = re.sub(r"导赏$", "正式演出", item_title)

        start_offset = OFFSET.search(tail)
        start = None
        end = None
        location = ""
        subsequent_time = None
        if time:
            start = time[1]
            end = time[2] if kind != "deadline" else None
            location = schedule_location(tail[time.end():], segment) if kind != "deadline" else ""
            if not location and kind != "deadline" and record.table and separator and separator[0] in {";", "；"}:
                next_part = DIVIDE.split(value[separator.end():], maxsplit=1)[0].strip()
                if not DATE.search(next_part) and not re.search(r"报名|登记|截止|对比|资格|回执|安排|仍待|未列|未注明|详情|公告|邮件", next_part):
                    location = schedule_location(next_part, next_part)
            if key == "sports-science-symposium" and not location:
                combined_location = re.search(r"GH201\s*(?:及|与|／|/)\s*FG Podium", segment)
                if combined_location:
                    location = combined_location[0]
        else:
            location = schedule_location(tail, segment) if kind != "deadline" else ""
        range_finish = None
        if following and time and not end and kind != "deadline" and re.fullmatch(r"\s*(?:至|到|[-–—])\s*", tail[time.end():]):
            after = value[following.match.end():segment_end]
            range_clock = TIME.match(after.lstrip())
            if range_clock:
                range_finish = following.days[0]
                end = range_clock[1]
                location = schedule_location(after.lstrip()[range_clock.end():], segment)
        if previous and time and re.search(rf"{CLOCK}\s*(?:至|到|[-–—])\s*$", value[previous.end():match.start()]):
            continue

        if time and time[2] and kind == "event":
            second_tail = tail[time.end():]
            for pair in TIME.finditer(second_tail):
                before = second_tail[:pair.start()]
                if not pair[2] or not re.search(r"[、，,]", before):
                    continue
                if re.search(r"报名|登记|截止|重合|冲突|收到|到达|收件|原发|恢复|午休", before):
                    continue
                if not VENUE.search(before) and not re.match(r"\s*[、，,]\s*$", before):
                    continue
                subsequent_time = (pair[1], pair[2], schedule_location(second_tail[pair.end():], segment))
                break

        for day in found.days:
            for begins, ends, where in [(start, end, location)] + ([subsequent_time] if subsequent_time else []):
                begins_at = normalize_time(day, begins, start_offset) if begins else None
                ends_at = normalize_time(range_finish or day, ends, start_offset) if ends else None
                if begins_at and ends_at and ends_at <= begins_at and range_finish is None:
                    ends_at += timedelta(days=1)
                event = {
                    "title": item_title, "category": record.category,
                    "start": begins_at.isoformat(timespec="minutes") if begins_at else day.isoformat(),
                    "end": ends_at.isoformat(timespec="minutes") if ends_at else None,
                    "all_day": begins_at is None,
                    "location": where,
                    "source_url": source_link(record, kind, item_title),
                    "mail_url": original_mail_link(record, item_title),
                    "source_date": record.day.isoformat(),
                    "notes": value.strip(" ·；")[:750],
                    "origin": "manual" if record.manual or "来源：用户于" in value else "mail",
                    "kind": kind,
                    "status": item_status(record, kind),
                }
                update = 3 if RESCHEDULED.search(left) else (2 if RESCHEDULED.search(segment) else 0)
                if begins:
                    update += 1
                output.append((event, key, update))
    return output


def text_key(value: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]", "", value.casefold())


def extract_events(markdown: str, today: date | None = None) -> list[dict]:
    """Return documented diary events ordered by Shanghai date and time."""
    today = today or datetime.now(SHANGHAI).date()
    results = {}
    aliases = {}
    for record in records(markdown):
        if record.day > today:
            continue
        for event, key, update in candidates(record):
            name = text_key(event["title"])
            if event["kind"] == "deadline" and (event["category"] == "assignment" or key in {"rise-scenario", "compcert-ai-video"}):
                signature = (event["category"], event["kind"], key or name)
            else:
                signature = (event["category"], event["kind"], key or name, event["start"])
            if event["category"] == "activity":
                registration = [url.casefold().rstrip("#") for label, url in record.links if re.search(r"报名|登记|注册|register|registration", label, re.I) and url.startswith(("http://", "https://"))]
                candidates_by_registration = [(event["kind"], url, event["start"]) for url in registration]
                for alternate in candidates_by_registration:
                    if alternate in aliases:
                        signature = aliases[alternate]
                        break
                for alternate in candidates_by_registration:
                    aliases[alternate] = signature
            old = results.get(signature)
            if old:
                previous, previous_update = old
                explicit_change = bool(update >= 2 and event["start"] != previous["start"])
                if event["start"] == previous["start"]:
                    use_new = (bool(event["source_url"]), event["source_date"], len(event["title"])) > (bool(previous["source_url"]), previous["source_date"], len(previous["title"]))
                elif event["start"][:10] == previous["start"][:10] and event["all_day"] != previous["all_day"]:
                    use_new = not event["all_day"]
                elif explicit_change or previous_update >= 2:
                    use_new = (update >= 2, event["source_date"], update) > (previous_update >= 2, previous["source_date"], previous_update)
                else:
                    use_new = (bool(event["source_url"]), event["source_date"], len(event["title"])) > (bool(previous["source_url"]), previous["source_date"], len(previous["title"]))
                if not use_new:
                    event, previous = previous, event
                    update = previous_update
                if not event["source_url"]:
                    event["source_url"] = previous["source_url"]
                if not event["mail_url"] and event["start"] == previous["start"]:
                    event["mail_url"] = previous["mail_url"]
                if not event["location"] and event["start"] == previous["start"]:
                    event["location"] = previous["location"]
                if not event["end"] and event["start"] == previous["start"]:
                    event["end"] = previous["end"]
                if previous["status"] in {"completed", "confirmed"}:
                    event["status"] = previous["status"]
            event["id"] = "diary-" + hashlib.sha256("|".join(signature).encode()).hexdigest()[:24]
            results[signature] = (event, update)
    return sorted((event for event, _ in results.values()), key=lambda event: (event["start"], event["title"]))
