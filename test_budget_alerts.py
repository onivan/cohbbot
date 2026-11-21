"""B3: перевірка порогу, збереження налаштування та атомарного антиспаму."""
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import database


class BudgetAlertSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.cursor = MagicMock()
        self.cursor.execute = AsyncMock()
        connection = MagicMock()
        connection.cursor.return_value.__aenter__.return_value = self.cursor
        for method in ('begin', 'commit', 'rollback'):
            setattr(connection, method, AsyncMock())
        self.connection = connection
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = connection
        self.pool = AsyncMock(return_value=pool)
        stack.enter_context(patch.object(database, 'get_pool', self.pool))

    async def test_missing_setting_defaults_to_ninety_percent(self):
        self.cursor.fetchone = AsyncMock(return_value=None)
        self.assertEqual(await database.get_budget_alert_threshold(), 90.0)
        self.cursor.execute.assert_awaited_once_with(
            'SELECT `value` FROM app_settings WHERE `key` = %s',
            ('budget_alert_threshold',),
        )

    async def test_saved_setting_is_returned_as_float(self):
        self.cursor.fetchone = AsyncMock(return_value=('75.5',))
        self.assertEqual(await database.get_budget_alert_threshold(), 75.5)

    async def test_invalid_stored_setting_falls_back_to_default(self):
        self.cursor.fetchone = AsyncMock(return_value=('invalid',))
        with self.assertLogs(level='ERROR'):
            self.assertEqual(await database.get_budget_alert_threshold(), 90.0)

    async def test_setting_write_is_upsert(self):
        self.assertEqual(await database.set_budget_alert_threshold(82.5), 82.5)
        sql, params = self.cursor.execute.call_args.args
        self.assertIn('INSERT INTO app_settings', sql)
        self.assertIn('ON DUPLICATE KEY UPDATE', sql)
        self.assertEqual(params, ('budget_alert_threshold', '82.5'))

    async def test_invalid_values_are_rejected_without_database_access(self):
        for value in (0, -1, 100.01, float('nan'), float('inf'), 'bad'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await database.set_budget_alert_threshold(value)
        self.pool.assert_not_awaited()

    async def test_alert_claim_uses_unique_scope_and_insert_ignore(self):
        self.cursor.rowcount = 1
        result = await database.claim_budget_alert(
            7, 'cat_food', '2026-11', 90, title='Досягнуто 90%',
            message='Поріг досягнуто', payload={'threshold': 90},
        )
        self.assertTrue(result)
        self.assertEqual(self.cursor.execute.await_count, 2)
        claim_sql, claim_params = self.cursor.execute.await_args_list[0].args
        self.assertIn('INSERT IGNORE INTO budget_alerts', claim_sql)
        self.assertEqual(claim_params, (7, 'cat_food', '2026-11', 90))
        event_sql, event_params = self.cursor.execute.await_args_list[1].args
        self.assertIn("VALUES ('budget_threshold'", event_sql)
        self.assertEqual(event_params[:3], ('Досягнуто 90%', 'Поріг досягнуто', 7))
        self.assertEqual(self.connection.commit.await_count, 1)

    async def test_duplicate_claim_returns_false(self):
        self.cursor.rowcount = 0
        self.assertFalse(await database.claim_budget_alert(
            7, 'cat_food', '2026-11', 90, title='Поріг', message='Досягнуто', payload={}))
        self.cursor.execute.assert_awaited_once()
        self.connection.rollback.assert_awaited_once()
        self.connection.commit.assert_not_awaited()

    async def test_failed_journal_insert_rolls_back_antispam_claim(self):
        self.cursor.rowcount = 1
        self.cursor.execute.side_effect = [None, RuntimeError('journal insert failed')]
        with self.assertRaises(RuntimeError):
            await database.claim_budget_alert(
                7, 'cat_food', '2026-11', 90, title='Поріг',
                message='Досягнуто', payload={'threshold': 90})
        self.connection.rollback.assert_awaited_once()
        self.connection.commit.assert_not_awaited()

    async def test_invalid_month_does_not_claim_alert(self):
        with self.assertRaises(ValueError):
            await database.claim_budget_alert(
                7, 'cat_food', '2026-13', 90, title='Поріг', message='Досягнуто', payload={})
        self.pool.assert_not_awaited()

    async def test_schema_creates_tables_unique_key_and_default(self):
        await database.ensure_budget_alert_schema()
        statements = [call.args[0] for call in self.cursor.execute.await_args_list]
        self.assertTrue(any('CREATE TABLE IF NOT EXISTS `app_settings`' in sql for sql in statements))
        self.assertTrue(any('CREATE TABLE IF NOT EXISTS `budget_alerts`' in sql
                            and 'uq_budget_alert' in sql for sql in statements))
        self.assertTrue(any('INSERT IGNORE INTO app_settings' in sql for sql in statements))
        self.assertEqual(self.cursor.execute.await_args_list[1].args[1],
                         ('budget_alert_threshold', '90.0'))
        self.assertEqual(len(statements), 3)


if __name__ == '__main__':
    unittest.main()
