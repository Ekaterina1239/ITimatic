# ITmatic Student Management System - Django + SQLite prototype

Built from the CW1 requirements (FR-01..05, UC-1..5, NFR-01..05) and the Figma hi-fi / lo-fi prototypes
(`ITmatic_Prototypes_hifi_lofi.docx`): sidebar workspace, phone + SMS sign-in with role picker, enrolment workspace,
week schedule, teacher absence, debtors, teacher phone form, parent account and absence wizard.

## Run
```
pip install django
python manage.py migrate
python manage.py seed            # 8 groups + IT group, ~75 students, this week's schedule, applicants
python manage.py runserver       # http://127.0.0.1:8765 (service worker / offline needs localhost or HTTPS)
python manage.py test            # 25 tests
python manage.py generate_fees   # monthly job (cron, 1st of month): charge fees, send reminders, "debtors list ready"
```
Sign in at `/login/` by phone. In demo mode the SMS code is shown on screen (`SMS_DEMO=True`; every SMS is also stored in `SMSLog`).

| Phone | Who | Roles |
|---|---|---|
| +998 90 100 00 01 | Alex Morgan | Administrator + Accountant (role picker, Figure 3) |
| +998 90 100 00 02 | Aziza Yusupova | Accountant |
| +998 90 200 00 05 | Nodira Karimova | Teacher (has the lesson that is open right now) |
| +998 90 200 00 01-04 | Turner, Reed, Bennett, Ellis | Teachers |
| +998 90 500 00 01 | Grace Wilson | Parent of 3 children |
| +998 90 600 00 01 | student | Student |

## Coverage
| ID | Where |
|---|---|
| FR-01 | `/enrolment/<id>/`: 6 stages in the design's order (level test 0-100 or skip with reason, teacher conversation Accepted/Not suitable, trial, student feedback, contract number+date+scan, add to group). Group step is locked until the contract is recorded (enforced in the view and in `Student.save`). Waiting list + 4-applicant notice, Lost with reason, follow-up list. Capacity 12 / 4 / 1. |
| FR-02 | Teacher form at `/attendance/` (same page on phone and laptop): opens 15 min before, read-only after 23:59, Present/Late/Absent, mark all present, topic, homework + due date, max 3 attachments, save draft. Missing-attendance report after 30 min. |
| FR-03 | `/absence/<student>/`: choose lesson -> Late (5/10/15/30/60) or Absent + reason -> optional period up to 14 days -> confirmation / withdraw. Refused after the lesson starts. Teacher sees the badge + gets a notification. |
| FR-04 | `/debtors/` for Administrator and Accountant (both record outcomes), longest overdue first, parent phone, amount in so'm, Take payment / Remind, outcome Promised by [date] / No answer / Leaving. `generate_fees` runs on the 1st. |
| FR-05 | `/account/`: child switcher, attendance, payment status + receipts, schedule, lesson materials, search. |
| UC-3 | `/payments/new/` cash/card/Payme/Click, partial payment, overpayment credit applied to later fees, printable receipt, discount requested by the accountant -> approved by the administrator approval. |
| UC-4 | `/teacher-absence/`: register absence, substitute (teacher + room clash check) or cancel, parents notified. Week grid marks room conflict, cover pending, make-up. |
| UC-5 | Phone + SMS login (6-digit code, 5 min, 5 attempts, 3 codes / 10 min, no account enumeration), parent with several children. |
| NFR-01 | 7 roles; one phone can hold several; active role chosen at sign-in; every view is role-checked; teachers only see their own groups/lessons; parents only their children. |
| NFR-02 | EN / RU / UZ for the whole interface and for SMS / notifications (sent in the recipient's language). |
| NFR-03 | Local IndexedDB on the device: lessons are copied down, attendance (with attachments) is saved locally and pushed later, idempotent, auto-sync <= 30 s after reconnect, conflict = newer server record wins. |
| NFR-04 | Mobile-first layout, 42 px tap targets, same form on phone and laptop. |
| NFR-05 | Indexed queries, WAL + `IMMEDIATE` transactions for concurrent staff, test with 220+ students (pages < 4 s). SQLite is for the prototype; use PostgreSQL in production. |

## Findings from analysing the design against the requirements
1. **UC-1 order differs from the design.** UC-1 picks the group at step 3 and has the *group's teacher* hold the conversation; the design puts "Add to group" last (after the contract) and the conversation before any group exists. The design is the safer order for FR-01 ("no group without contract"); update UC-1 text to match.
2. **FR-04 says admin only, the design lets the accountant open Debtors** (select-role screen, lo-fi flow 3). Implemented: admin and accountant can view, only admin records Promised / No answer / Leaving. Decide which is intended.
3. **The design's debtors table has no Promised / No answer / Leaving control** - FR-04 requires it. Added.
4. **Branches (Chilonzor / Yunusobod) and the Education manager "certificate approval" flow appear in the design but in no requirement or use case.** Implemented minimally (branch on groups/rooms/applicants; certificate = attendance >= 85% and average >= 60, thresholds in settings are my assumption). Add FR/UC for them.
5. **The design's teacher form has "Due date" and "Save draft", and one "Choose file"** - FR-02 asks for up to 3 attachments. Implemented 3.
6. **Lo-fi/hi-fi teacher menu shows "Messages" and "Settings"** with no requirement behind them. Not built.
7. **"Trial: Did not attend"** has no defined next step in UC-1. The stage stays open until the admin records attendance or closes as Lost.
8. NFR-05 "Scalability" is still not measurable (no target number of branches, students, concurrent users).
9. Missing for production: SMS gateway choice (Eskiz / Playmobile), Payme/Click online integration (payments are entered manually with a transaction number), contract/scan retention and parental-consent rules for minors' data.

## Known limits of the prototype
`SMS_DEMO=True` shows login codes on screen and `SECRET_KEY` / `DEBUG` are development values - change before any real use.
Contract scans and attachments are stored on local disk (`media/`). A few server error sentences that contain numbers (e.g. room-busy messages) are English only.
Offline conflicts are resolved by timestamp only (no merge screen). The device keeps lessons from 2 days back to 7 days ahead.
Administrators can correct attendance after 23:59; teachers cannot (FR-02 read-only rule applies to teachers).


## Scope update (latest decisions)
- Roles: administrator, accountant, teacher, parent, student. Director and education manager removed; the administrator approves discounts and substitutes.
- UC-1 order: level test -> conversation -> trial -> feedback -> contract -> group. Each step is blocked until the previous one is done; no group without a signed contract.
- FR-02: the device timestamp decides whether an offline record is accepted; read-only after 23:59, but the administrator can correct attendance later.
- Waiting list: `WAITLIST_MIN = {"standard": 6, "mini": 3}` in settings; applicants carry the preferred group type.
- Removed for now: grades entry, certificates, branch UI (the `branch` field stays on Group/Room/Applicant so branches can be added later), detailed fee rules, audit log, freeze/leave flows.
- Still to clarify with the business: who may mark absences and the exact 14-day rules, shared phone numbers, Telegram as preferred notification channel (SMS is the fallback today).
- Group capacity is derived from physical space: `min(limit by type 12/4/1, room.seats)` (see `Group.capacity`, `Room.seats`).
