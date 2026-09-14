# Local demo sign-in

The isolated browser-test host supports officer@astra.test and surveyor@astra.test.
Passwords are generated once in ignored data/ui-test/demo-credentials.json. Keep
that local credential file private; it contains the demonstration passwords.
Password verification uses salted scrypt hashes. Successful sign-in issues a
four-hour signed JWT; the normal API verifies it and reads membership from the
database. Restarting the test host invalidates existing sessions.

Open http://127.0.0.1:3000 and enter the account credentials. These are local demo
accounts only, not Supabase or government accounts. The demo endpoints exist
only in backend/tests/ui_server.py, which requires ASTRA_UI_TEST=1,
ENVIRONMENT=test and the dedicated astra_ui_test database. Production Supabase
sign-in takes priority when configured. The local login limits attempts to 20
per minute across accounts.

Run the browser checks with npm run e2e --prefix frontend -- demo-login.spec.ts
while the frontend and isolated backend are running.
