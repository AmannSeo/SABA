"""수신자·그룹 관리 (D-074, D-075). 모든 주소는 가상이다."""

from pathlib import Path
import tempfile
import unittest

from saba import recipients as rc
from saba.send_mail import TEST_ADDRESS, SendError, prepare

A = ("가상 사용자 하나", "virtual.one@tbell.co.kr", "보안사업팀", ["TEST"])


class RecipientTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "recipients.db"

    def test_defaults(self):
        self.assertEqual([g for g, _ in rc.groups(self.db)], ["전체", "TEST", "파일럿"])
        self.assertEqual([d for d, _ in rc.departments(self.db)], ["경영전략팀", "기술개발연구소", "보안사업팀", "STE본부"])
        self.assertEqual(rc.domains(self.db), ["tbell.co.kr"])

    def test_add_edit_disable_delete(self):
        self.assertEqual(rc.save(*A, path=self.db), "추가")
        person = rc.recipients(self.db)[0]
        self.assertEqual((person.email, person.groups, person.enabled), ("virtual.one@tbell.co.kr", ["TEST"], True))
        rc.save("가상 사용자 하나", "Virtual.One@TBELL.co.kr", "STE본부", ["TEST", "파일럿"], recipient_id=person.id, path=self.db)
        person = rc.recipients(self.db)[0]
        self.assertEqual((person.department, person.groups), ("STE본부", ["TEST", "파일럿"]))
        rc.set_enabled(person.id, False, self.db)
        self.assertEqual(rc.recipients(self.db, "전체"), [])  # 전체 = 사용 중인 전원
        self.assertEqual(rc.groups(self.db)[1], ("TEST", 0))
        rc.delete(person.id, self.db)
        self.assertEqual(rc.recipients(self.db), [])

    def test_validation(self):
        rc.save(*A, path=self.db)
        bad = [("", "virtual.two@tbell.co.kr", "보안사업팀", []),
               ("가상", "not-an-email", "보안사업팀", []),
               ("가상", "virtual.two@gmail.com", "보안사업팀", []),  # 회사 도메인만
               ("가상", "virtual.two@tbell.co.kr", "없는부서", []),
               ("가상", "virtual.two@tbell.co.kr", "보안사업팀", ["없는그룹"]),
               ("가상", "virtual.one@tbell.co.kr", "보안사업팀", [])]  # 중복
        for args in bad:
            with self.subTest(args=args), self.assertRaises(rc.RecipientError):
                rc.save(*args, path=self.db)
        rc.add_domain("@partner.example", self.db)
        rc.save("협력사", "virtual.three@partner.example", "보안사업팀", [], path=self.db)

    def test_groups_departments_domains(self):
        rc.add_group("임원", self.db)
        self.assertRaises(rc.RecipientError, rc.add_group, "전체", self.db)
        self.assertRaises(rc.RecipientError, rc.delete_group, "TEST", self.db)
        rc.save("가상", "virtual.four@tbell.co.kr", "보안사업팀", ["임원"], path=self.db)
        rc.delete_group("임원", self.db)
        self.assertEqual(rc.recipients(self.db)[0].groups, [])  # 소속도 함께 지움
        rc.add_department("인사팀", self.db)
        self.assertRaises(rc.RecipientError, rc.delete_department, "보안사업팀", self.db)  # 쓰는 수신자 있음
        rc.delete_department("인사팀", self.db)
        self.assertRaises(rc.RecipientError, rc.delete_domain, "tbell.co.kr", self.db)  # 마지막 도메인

    def test_csv_preview_and_apply(self):
        rc.save(*A, path=self.db)
        text = ("\ufeff이름,메일,부서,그룹\n"
                "가상 하나 수정,virtual.one@tbell.co.kr,STE본부,TEST\n"
                "가상 둘,virtual.two@tbell.co.kr,기술개발연구소,TEST;파일럿\n"
                "가상 셋,virtual.three@gmail.com,보안사업팀,\n"
                "가상 넷,virtual.two@tbell.co.kr,보안사업팀,\n"
                "가상 다섯,virtual.five@tbell.co.kr,없는부서,\n")
        rows = rc.parse_csv(text, self.db)
        self.assertEqual([r["status"] for r in rows], ["갱신", "신규", "오류", "오류", "오류"])
        self.assertEqual(len(rc.recipients(self.db)), 1)  # 미리보기는 저장하지 않음
        self.assertEqual(rc.apply_csv(rows, self.db), (1, 1, 3))
        people = {r.email: r for r in rc.recipients(self.db)}
        self.assertEqual(people["virtual.one@tbell.co.kr"].department, "STE본부")
        self.assertEqual(people["virtual.two@tbell.co.kr"].groups, ["TEST", "파일럿"])

    def test_tab_paste_and_export(self):
        rows = rc.parse_csv("가상 탭\tvirtual.tab@tbell.co.kr\t보안사업팀\tTEST", self.db)
        self.assertEqual(rows[0]["status"], "신규")
        rc.apply_csv(rows, self.db)
        exported = rc.export_csv(self.db)
        self.assertTrue(exported.startswith("\ufeff이름,메일,부서,그룹,상태"))
        self.assertIn("가상 탭,virtual.tab@tbell.co.kr,보안사업팀,TEST,사용", exported)
        self.assertEqual(rc.parse_csv(rc.template_csv(), self.db)[0]["status"], "신규")

    def test_sending_still_test_address_only(self):  # 수신자를 저장해도 발송 경로는 TEST 1명만 (D-074)
        from email.message import EmailMessage
        rc.save(*A, path=self.db)
        message = EmailMessage()
        message["To"] = "virtual.one@tbell.co.kr"
        with self.assertRaises(SendError):
            prepare(message)
        self.assertEqual(prepare(EmailMessage())["To"], TEST_ADDRESS)


if __name__ == "__main__":
    unittest.main()
