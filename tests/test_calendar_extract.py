import unittest
from datetime import date

from calendar_extract import extract_events


TODAY = date(2026, 11, 15)


class ExtractEventsTest(unittest.TestCase):
    def extract(self, markdown):
        return extract_events(markdown, TODAY)

    def test_assignment_extension_and_reminders_preserve_the_source(self):
        events = self.extract(
            """
# 2026-11-15
## 作业任务
- **Quiz 7 原列今天 23:55 截止**。COMP5584 A2 延期后的截止为 **11 月 18 日 23:59**。
# 2026-11-14
## 作业任务
- **Quiz 7 原列明天 11 月 15 日 23:55 截止**。18:29:19 收到 Canvas 周报，补列 **COMP5584 A2 延期后的截止为 11 月 18 日 23:59**。[A2 作业入口](https://canvas.example/courses/1/assignments/1) · [周报](https://mail.google.com/mail/#all/new)
- [ ] **完成学术诚信课程 Quiz 8**。Canvas 周报列 **11 月 22 日 23:55 截止**。[Quiz 8 入口](https://canvas.example/courses/2/assignments/8)
# 2026-10-17
## 作业任务
- [ ] **COMP5584 Assignment 2**：Canvas 周报注明截止 **2026-11-11 23:59**。
  - **11 月 11 日延期更新**。公告将原 **11 月 11 日 23:59** 截止改至 **11 月 18 日（周三）**，新时刻未注明。
"""
        )
        deadlines = {event["title"]: event for event in events}
        self.assertEqual(len(events), 3)
        self.assertEqual(deadlines["Quiz 7"]["start"], "2026-11-15T23:55")
        self.assertEqual(deadlines["Quiz 8"]["start"], "2026-11-22T23:55")
        a2 = deadlines["COMP5584 A2"]
        self.assertEqual(a2["start"], "2026-11-18T23:59")
        self.assertEqual(a2["source_date"], "2026-11-14")
        self.assertTrue(a2["source_url"].endswith("/assignments/1"))
        self.assertEqual(a2["mail_url"], "https://mail.google.com/mail/#all/new")
        self.assertEqual(deadlines["Quiz 8"]["mail_url"], "")

    def test_original_email_requires_a_message_link_and_matches_named_sources(self):
        events = self.extract(
            """
# 2026-11-15
## 作业任务
- **COMP5584 A2**。截止 **2026-11-18 23:59**。[作业入口](https://canvas.example/assignments/2) · [COMP5584 A2 通知](https://mail.google.com/mail/u/?authuser=student%40example.com#all/A2-message) · [Quiz 8 通知](https://mail.google.com/mail/u/0/#inbox/quiz-message)
- **Quiz 7**。截止 **2026-11-17 23:55**。[Gmail 首页](https://mail.google.com/mail/u/0/#inbox) · [邮件](https://mail.google.com.example/mail/#all/spoof)
- **Quiz 8**。截止 **2026-11-20 23:55**。[邮件一](https://mail.google.com/mail/#all/one) · [邮件二](https://mail.google.com/mail/#all/two)
"""
        )
        by_title = {event["title"]: event for event in events}
        self.assertEqual(by_title["COMP5584 A2"]["mail_url"], "https://mail.google.com/mail/u/?authuser=student%40example.com#all/A2-message")
        self.assertEqual(by_title["Quiz 7"]["mail_url"], "")
        self.assertEqual(by_title["Quiz 8"]["mail_url"], "")

    def test_email_is_reused_for_matching_occurrence_only(self):
        events = self.extract(
            """
# 2026-11-15
## 作业任务
- **COMP5584 A2**。截止 **2026-11-18 23:59**。[作业入口](https://canvas.example/assignments/2)
- **COMP5584 A3**。延期后的截止为 **2026-11-25 23:59**。[作业入口](https://canvas.example/assignments/3)
# 2026-11-14
## 作业任务
- **COMP5584 A2**。截止 **2026-11-18 23:59**。[邮件](https://mail.google.com/mail/#all/A2-message)
- **COMP5584 A3**。截止 **2026-11-21 23:59**。[旧邮件](https://mail.google.com/mail/#all/A3-old-message)
"""
        )
        by_title = {event["title"]: event for event in events}
        self.assertEqual(by_title["COMP5584 A2"]["mail_url"], "https://mail.google.com/mail/#all/A2-message")
        self.assertEqual(by_title["COMP5584 A3"]["start"], "2026-11-25T23:59")
        self.assertEqual(by_title["COMP5584 A3"]["mail_url"], "")

    def test_two_sessions_two_venues_and_booking_deadline(self):
        events = self.extract(
            """
# 2026-11-12
## 活动
- **校企研讨会**。11:31:30 收件，**11 月 20 日 09:00–12:00 理大 BC301、14:30–18:00 理大 Z407，另设 Zoom**。**11 月 18 日或之前**报名。上午与其他会议重合 **10:45–12:00**。[报名](https://example.org/signup)
"""
        )
        self.assertEqual([event["start"] for event in events], ["2026-11-18", "2026-11-20T09:00", "2026-11-20T14:30"])
        self.assertEqual([event["location"] for event in events[1:]], ["理大 BC301", "理大 Z407"])
        self.assertEqual([event["status"] for event in events], ["invitation"] * 3)
        self.assertEqual(events[0]["kind"], "deadline")
        self.assertTrue(events[0]["all_day"])

    def test_life_closure_restoration_and_billing_without_transaction_history(self):
        events = self.extract(
            """
# 2026-11-15
## 生活
- **FCMS 柜台**明天 11 月 16 日全天暂停，17 日 15:00 恢复。[通知](https://mail.google.com/mail/#all/current)
- **银行自动扣账已执行**。交易日期为 **11 月 15 日**。
- **手机账单**。缴款日期 **2026-11-30**。
- **信用卡条款修订**。**2027 年 1 月 17 日生效**。
"""
        )
        self.assertEqual([(event["kind"], event["start"]) for event in events], [
            ("notice", "2026-11-16"),
            ("notice", "2026-11-17T15:00"),
            ("deadline", "2026-11-30"),
            ("notice", "2027-01-17"),
        ])

    def test_repeated_invite_and_confirmation_share_one_event(self):
        events = self.extract(
            """
# 2026-11-15
## 活动
- **本地工作坊提醒**。仍为 **11 月 21 日 02:00–04:00 UTC+0，Zoom**。成功登记者另发确认。[报名](https://example.org/signup) · [提醒邮件](https://mail.google.com/mail/#all/new)
# 2026-11-12
## 活动
- **已报名：社区工作坊**。**11 月 21 日 10:00–12:00 HKT，Zoom**。已收到个人报名确认。[报名](https://example.org/signup) · [确认](https://mail.google.com/mail/#all/old)
"""
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["start"], "2026-11-21T10:00")
        self.assertEqual(events[0]["end"], "2026-11-21T12:00")
        self.assertEqual(events[0]["status"], "confirmed")
        self.assertEqual(events[0]["source_url"], "https://mail.google.com/mail/#all/new")

    def test_manual_schedule_does_not_pick_up_provenance_dates(self):
        events = self.extract(
            """
# 2026-10-22
## 作业任务
- [x] **UX 答辩**：2026-10-26（周一，下周一）；具体时间、地点待补充。来源：用户于 2026-10-22 补充。
- [ ] **元宇宙经济**：2026-10-30（周五）；具体事项形式、时间、地点待补充。来源：用户于 2026-10-22 补充。
- [ ] **XR 期中考试**：2026-11-03（周二）**18:30–21:30，PQ604A/B/C**；来源：用户于 2026-10-22 提供日期，10 月 28 日课程公告补齐时刻地点与要求，10 月 29 日实际查阅后更新。
- [ ] **核对并保存个人期末考试时间表**：考试期为 **2026 年 12 月 3–18 日**，没有把统一考试期当成本人的具体考试安排。
"""
        )
        self.assertEqual([event["start"] for event in events], ["2026-10-26", "2026-10-30", "2026-11-03T18:30"])
        self.assertEqual(events[0]["status"], "completed")
        self.assertEqual(events[2]["location"], "PQ604A/B/C")

    def test_markdown_sections_exclude_check_log_and_include_table(self):
        events = self.extract(
            """
# 2026-11-13
## 活动
| 活动 | 时间与地点 | 来源 |
| --- | --- | --- |
| 港韩数学金融工作坊 | 11 月 20–21 日每天 09:00–18:00；AG710 | [邮件](https://mail.google.com/mail/#all/invitation) |
## 更新记录
- **本批更新**。**11 月 19 日 02:00 截止**。
"""
        )
        self.assertEqual([event["start"] for event in events], ["2026-11-20T09:00", "2026-11-21T09:00"])
        self.assertTrue(all(event["location"] == "AG710" for event in events))
        self.assertEqual(len({event["id"] for event in events}), 2)


if __name__ == "__main__":
    unittest.main()
