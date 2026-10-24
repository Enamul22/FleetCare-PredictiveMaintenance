# Manual deployment checklist

Application owner and repository owner: Enamul Haque / Enamul22 (GitHub ID 135505234).
No hosting deployment was performed. Enamul will review first.

- Review README, evaluation misses, screenshots, and passing GitHub Actions run for the delivered commit.
- Confirm repository `Enamul22/FleetCare-PredictiveMaintenance`, branch `main`, entry point `app.py`.
- Streamlit Community Cloud: sign in using Enamul's connection. Do not use Priynka's deployment account.
- Create app manually; select that repository/branch/main file. Advanced settings: Python 3.12.
- `requirements.txt` is at repository root; no private files, secrets or paid services are required.
- Leave `FLEETCARE_MODE` unset (defaults to session). Never enable local shared-file mode for public visitors.
- Confirm package installation, overview, filters, all five views and one complete repair/verification loop.
- Confirm two independent visitor sessions have independent incidents/feedback; reset clears only one session.
- Do not run full generation or offline evaluation in the hosted startup path.
- Treat hosted session changes as disposable. External durable storage is a documented extension, not implemented.
- Publish no real customer notifications; every CRM/ERP/service action here is local simulated writeback.
- If redeploying, deploy the reviewed commit; compare CI and manifest hashes. A new detector/policy requires
  development evaluation and a newly reserved untouched holdout before promotion.
