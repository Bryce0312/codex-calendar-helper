from datetime import datetime, timedelta, timezone
import unittest

from calendar_voice import parse_schedule


class VoiceScheduleTests(unittest.TestCase):
    def setUp(self):
        # The reference date is a Sunday in Shanghai.
        self.now = datetime(2026, 11, 15, 20, tzinfo=timezone(timedelta(hours=8)))

    def test_relative_day_chinese_clock_and_location(self):
        result = parse_schedule("帮我加一个日程，明天下午三点半到五点在图书馆开会", self.now)
        self.assertEqual(result["draft"], {
            "title": "开会",
            "category": "life",
            "kind": "event",
            "start": "2026-11-16T15:30",
            "end": "2026-11-16T17:00",
            "all_day": False,
            "location": "图书馆",
            "notes": "",
        })
        self.assertEqual(result["warnings"], [])

    def test_documented_group_meeting_phrase(self):
        result = parse_schedule("明天下午三点到四点，在图书馆开组会", self.now)
        draft = result["draft"]
        self.assertEqual(draft["title"], "开组会")
        self.assertEqual(draft["category"], "activity")
        self.assertEqual(draft["location"], "图书馆")
        self.assertEqual(draft["start"], "2026-11-16T15:00")
        self.assertEqual(draft["end"], "2026-11-16T16:00")
        self.assertEqual(result["warnings"], [])

    def test_weekday_and_compact_course_name(self):
        draft = parse_schedule("下周三晚上七点到八点交COMP5584 A2", self.now)["draft"]
        self.assertEqual(draft["title"], "交COMP5584 A2")
        self.assertEqual(draft["category"], "assignment")
        self.assertEqual(draft["start"], "2026-11-18T19:00")
        self.assertEqual(draft["end"], "2026-11-18T20:00")

    def test_spoken_year_and_quarters(self):
        draft = parse_schedule("二零二六年十一月十八日下午三点一刻至四点三刻参加讲座", self.now)["draft"]
        self.assertEqual(draft["category"], "activity")
        self.assertEqual(draft["start"], "2026-11-18T15:15")
        self.assertEqual(draft["end"], "2026-11-18T16:45")

    def test_short_range_and_explicit_place(self):
        draft = parse_schedule("周一从下午2到4点上课，地点：Y302，备注带电脑", self.now)["draft"]
        self.assertEqual(draft["title"], "上课")
        self.assertEqual(draft["category"], "assignment")
        self.assertEqual(draft["start"], "2026-11-16T14:00")
        self.assertEqual(draft["end"], "2026-11-16T16:00")
        self.assertEqual(draft["location"], "Y302")
        self.assertEqual(draft["notes"], "带电脑")

    def test_evening_alias_and_overnight_range(self):
        result = parse_schedule("今晚十一点到凌晨一点线上开会", self.now)
        self.assertEqual(result["draft"]["start"], "2026-11-15T23:00")
        self.assertEqual(result["draft"]["end"], "2026-11-16T01:00")
        self.assertTrue(result["warnings"])

    def test_explicit_date_with_iso_delimiter(self):
        draft = parse_schedule("２０２６-１１-１８Ｔ１５：３０ 图书馆讲座", self.now)["draft"]
        self.assertEqual(draft["start"], "2026-11-18T15:30")
        self.assertEqual(draft["title"], "图书馆讲座")

    def test_short_dotted_date_with_date_suffix(self):
        draft = parse_schedule("11.18号下午四点XR考试", self.now)["draft"]
        self.assertEqual(draft["start"], "2026-11-18T16:00")
        self.assertEqual(draft["category"], "assignment")

    def test_day_only_draft_and_registration_category(self):
        draft = parse_schedule("明年一月十七日工作坊报名截止", self.now)["draft"]
        self.assertEqual(draft["category"], "activity")
        self.assertEqual(draft["kind"], "deadline")
        self.assertEqual(draft["start"], "2027-01-17")
        self.assertIsNone(draft["end"])
        self.assertTrue(draft["all_day"])

    def test_explicit_ddl(self):
        draft = parse_schedule("明天23:59 COMP5584 DDL", self.now)["draft"]
        self.assertEqual(draft["category"], "assignment")
        self.assertEqual(draft["kind"], "deadline")
        self.assertEqual(draft["start"], "2026-11-16T23:59")

    def test_missing_date_stays_empty(self):
        result = parse_schedule("下午三点交作业", self.now)
        self.assertEqual(result["draft"]["start"], "")
        self.assertFalse(result["draft"]["all_day"])
        self.assertTrue(result["warnings"])

    def test_daypart_requires_confirmation(self):
        result = parse_schedule("明天上午在线参加讲座", self.now)
        self.assertEqual(result["draft"]["title"], "在线参加讲座")
        self.assertEqual(result["draft"]["location"], "")
        self.assertEqual(result["draft"]["start"], "2026-11-16")
        self.assertTrue(result["warnings"])

    def test_invalid_date_or_backwards_time_range(self):
        invalid = parse_schedule("二月三十日交作业", self.now)
        self.assertEqual(invalid["draft"]["start"], "")
        self.assertTrue(invalid["warnings"])
        backwards = parse_schedule("明天下午三点到两点考试", self.now)
        self.assertEqual(backwards["draft"]["start"], "2026-11-16T15:00")
        self.assertIsNone(backwards["draft"]["end"])
        self.assertTrue(backwards["warnings"])
