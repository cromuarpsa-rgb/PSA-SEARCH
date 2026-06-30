PSA Search System

How to run:
1. Double-click run.bat.
2. Open http://127.0.0.1:8000 in your browser.
3. Log in with:
   Username: admin
   Password: admin123

Data source:
- The system reads the newest .xlsx file inside the data folder.
- All workbook sheets are loaded and can be searched together or one sheet at a time.

Logs:
- Login, logout, search, and error events are saved in logs/activity.log.

Notes:
- The app is pure Python and uses only the Python standard library.
- Search is automatic: type one or more keywords and the table filters immediately.
