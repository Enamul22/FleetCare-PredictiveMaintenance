# Review evidence · two-workspace update

24 October 2026, Chrome, fresh isolated shared review SQLite store. Synthetic public demo logins only.

- Admin native dataframe selection opened VEH-0426 / CUS-0085 and the correct measured chart,
  Recommended actions and Parts list tabs. Explicit Create produced WO-CE08330A437BD5EB.
- A separately signed-in customer0085 session saw exactly its assigned Open order and submitted
  Completed / Unknown finding and cause / Inspection / Not resolved / rating 4 / exact notes containing
  “partial”. Admin Refresh showed the same saved response; the fault remained Active.
- Admin selected VEH-0639 / CUS-0127 after filtering. Customer0127 saw only its own assigned order.
  Rejection without reason visibly failed; valid rejection saved its reason/notes, no rating or fabricated
  work. Admin refresh read it back. Rejected history retained the order.
- Pagination reached page 2/3, search reset to page 1/1 for one matching row, and Back preserved that search.
- Browser CSV download contained all 70 unique episode IDs, including both exact responses; null
  feedback remained empty. Automated tests additionally verify arbitrary filters, direct foreign ID/evidence
  access denial, retries/concurrency, all five families, ended-before-response and legacy preservation.
- Responsive customer history was reviewed at 390×844; the temporary viewport override was reset.
  Tables retain horizontal scrolling for detailed columns. No hosting deployment was performed.

Screenshots are current application captures:

| File | Evidence |
|---|---|
| overview-header.jpg | Admin heading, source coverage, filters and measured counts |
| overview-wide.jpg | Complete counts, page control and populated selectable fleet table |
| fault-detail.jpg | Selected vehicle/customer, independent statuses and order link above tabs |
| incident-evidence.jpg | Actual supporting sensor chart, legend/boundaries and evidence context |
| work-order.jpg | Customer saved recommendation and proposed parts |
| feedback.jpg | Completed technical response form |
| admin-writeback.jpg | Exact customer response visible after admin refresh |
| rejection.jpg | Saved rejected reason, notes and null rating |
| overview-narrow.jpg | Customer rejected history, 390×844 |
| signin.jpg | Modest credential sign-in with no role assertion control |

The screenshots include browser-review order data only. A fresh clone starts with 70 faults and zero
orders/responses, not the review DB. Obsolete five-view evaluation/recovery screenshots were removed from
primary evidence; Git history retains them. Historical detector reports remain in evaluation/historical.

local-tests.xml records 36 passing local tests. evaluation/report.json and operational.json record separate
measured detector and five-family service checks. Exact clean-setup and remote Actions results are recorded
in PROGRESS.md and the final handoff. This evidence does not establish production readiness or real repair
success.

## 27 October 2026 · local clarity follow-up

A real Chrome sign-out/sign-in retained customer0085's completed order and response in the shared local
review store. history-after-login.jpg shows the new counts and Open-filter explanation;
history-all-orders.jpg shows the history shortcut selecting All and the retained completed row.
customer-evidence-explanation.jpg shows plain-language trigger/recovery explanation and readable UTC dates.
These local checks do not diagnose or fix reported missing records on the deployed app. Hosted local
SQLite persistence remains unguaranteed. Follow-up code/screenshots remain local for review, without a
GitHub push or hosting mutation.
