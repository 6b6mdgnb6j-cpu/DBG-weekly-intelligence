# Manual Translation Fallback

Use this only when Production reports a blocking translation QA failure.

1. Run Production for the required week.
2. Download the `manual-translation-queue-YYYY-MM-DD` artifact.
3. Open `manual_translation_queue_YYYYMMDD.xlsx`.
4. Edit **only** the `Manual Translation` column.
5. Save the workbook with the same filename.
6. Put it in `manual_translations/inbox/`.
7. Run `python3 scripts/apply_manual_translations.py --week-start YYYY-MM-DD`.
8. If QA passes, commit only `manual_translations/approved/weekly_YYYYMMDD.json`.
9. Push the commit.
10. Rerun Production for the same week.

ChatGPT membership and the OpenAI API are not required. Any reliable human or
translation tool may be used to draft the Chinese text. The project's normal QA,
not the drafting tool, makes the final acceptance decision.
