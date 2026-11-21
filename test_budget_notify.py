"""B2/B4: сповіщення й точки виклику без реальних записів у БД або Telegram."""
import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import budget_notify
import database


class BudgetNotifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.budgets = stack.enter_context(patch.object(
            database, 'get_center_budgets', AsyncMock(return_value={'cat_food': 100.0})))
        self.spent = stack.enter_context(patch.object(
            database, 'get_category_spent', AsyncMock(return_value=120.5)))
        self.threshold = stack.enter_context(patch.object(
            database, 'get_budget_alert_threshold', AsyncMock(return_value=90.0)))
        self.claim = stack.enter_context(patch.object(
            database, 'claim_budget_alert', AsyncMock(return_value=False)))
        stack.enter_context(patch.object(database, 'get_all_categories', AsyncMock(
            return_value=[{'id': 'cat_food', 'name': 'Харчування <тест>'}])))
        stack.enter_context(patch.object(database, 'get_centers', AsyncMock(
            return_value=[{'id': 7, 'name': 'Тестовий ЦН'}])))
        self.journal = stack.enter_context(patch.object(
            database, 'create_admin_notification', AsyncMock(return_value=1)))
        self.send = stack.enter_context(patch.object(budget_notify.bot, 'send_message', AsyncMock()))
        stack.enter_context(patch.object(database, 'users_cache', {
            '1': {'center_id': 7, 'status': 'active', 'role': 'user'},
            '2': {'center_id': '7', 'status': 'active', 'role': 'admin'},
            '3': {'center_id': 8, 'status': 'active', 'role': 'user'},
            '4': {'center_id': 7, 'status': 'blocked', 'role': 'user'},
            '5': {'center_id': 7, 'status': 'pending', 'role': 'user'},
        }))

    async def notify(self, amount=0):
        await budget_notify.notify_overrun(7, 'cat_food', '2026-10', 'exp_test', amount)

    async def test_missing_budget_is_not_zero_budget(self):
        self.budgets.return_value = {}
        await self.notify()
        self.spent.assert_not_awaited()
        self.journal.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_below_or_equal_budget_is_silent(self):
        for spent in (0, 99.99, 100):
            with self.subTest(spent=spent):
                self.spent.return_value = spent
                await self.notify()
        self.journal.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_overrun_records_scope_and_notifies_only_active_center_users(self):
        await self.notify()
        self.spent.assert_awaited_once_with(7, 'cat_food', '2026-10')
        self.budgets.assert_awaited_once_with(7, '2026-10')
        event = self.journal.call_args.kwargs
        self.assertEqual(event['type'], 'budget_overrun')
        self.assertEqual(event['center_id'], 7)
        self.assertEqual(event['action_status'], 'resolved')
        self.assertEqual(event['payload'], {
            'expense_id': 'exp_test', 'month': '2026-10',
            'category_id': 'cat_food', 'category_name': 'Харчування <тест>',
            'spent': 120.5, 'budget': 100.0,
        })
        self.assertEqual([c.args[0] for c in self.send.await_args_list], [1, 2])
        self.assertIn('120,50/100,00 грн', self.send.call_args.args[1])
        self.assertIn('2026-10', self.send.call_args.args[1])
        self.assertIsNone(self.send.call_args.kwargs['parse_mode'])

    async def test_explicit_zero_budget_warns(self):
        self.budgets.return_value = {'cat_food': 0.0}
        await self.notify()
        self.journal.assert_awaited_once()
        self.assertEqual(self.journal.call_args.kwargs['payload']['budget'], 0.0)
        self.claim.assert_not_awaited()

    async def test_telegram_failure_does_not_stop_other_recipients(self):
        self.send.side_effect = [RuntimeError('test send failure'), None]
        with self.assertLogs(level='ERROR'):
            await self.notify()
        self.assertEqual(self.send.await_count, 2)
        self.journal.assert_awaited_once()

    async def test_journal_failure_does_not_stop_telegram(self):
        self.journal.side_effect = RuntimeError('test journal failure')
        with self.assertLogs(level='ERROR'):
            await self.notify()
        self.assertEqual(self.send.await_count, 2)

    async def test_database_failure_is_contained(self):
        self.spent.side_effect = RuntimeError('test query failure')
        with self.assertLogs(level='ERROR'):
            await self.notify()
        self.send.assert_not_awaited()

    async def test_threshold_setting_failure_does_not_disable_overrun_warning(self):
        self.threshold.side_effect = RuntimeError('settings table unavailable')
        with self.assertLogs(level='ERROR'):
            await self.notify()
        self.journal.assert_awaited_once()
        self.assertEqual(self.journal.call_args.kwargs['type'], 'budget_overrun')
        self.assertEqual(self.send.await_count, 2)

    async def test_journal_still_created_without_recipients(self):
        with patch.object(database, 'users_cache', {}):
            await self.notify()
        self.journal.assert_awaited_once()
        self.send.assert_not_awaited()

    async def test_threshold_crossing_records_one_admin_event_and_sends_telegram(self):
        self.spent.return_value = 90.0
        self.claim.return_value = True
        with patch('telegram_notifications.notify_admins', new_callable=AsyncMock) as notify_admins:
            await self.notify(amount=1.0)
        self.journal.assert_not_awaited()
        self.claim.assert_awaited_once()
        claim = self.claim.call_args.kwargs
        self.assertEqual(self.claim.call_args.args, (7, 'cat_food', '2026-10', 90.0))
        self.assertEqual(claim['title'], 'Досягнуто 90% ліміту')
        self.assertEqual(claim['payload']['threshold'], 90.0)
        self.assertEqual(claim['payload']['expense_id'], 'exp_test')
        notify_admins.assert_awaited_once()
        self.assertIn('Досягнуто 90% ліміту', notify_admins.call_args.args[0])
        self.send.assert_not_awaited()

    async def test_threshold_not_sent_if_spend_does_not_cross(self):
        cases = [(89.99, 1.0), (90.5, 0.5), (120.0, 0.0)]
        for spent, amount in cases:
            with self.subTest(spent=spent, amount=amount):
                self.spent.return_value = spent
                await self.notify(amount=amount)
        self.claim.assert_not_awaited()
        self.journal.assert_not_awaited()

    async def test_duplicate_threshold_claim_suppresses_admin_message_and_event(self):
        self.spent.return_value = 95
        self.claim.return_value = False
        with patch('telegram_notifications.notify_admins', new_callable=AsyncMock) as notify_admins:
            await self.notify(amount=10)
        self.claim.assert_awaited_once()
        self.assertEqual(self.claim.call_args.args, (7, 'cat_food', '2026-10', 90.0))
        self.journal.assert_not_awaited()
        notify_admins.assert_not_awaited()

    async def test_threshold_claim_database_error_does_not_send_duplicate(self):
        self.spent.return_value = 95
        self.claim.side_effect = RuntimeError('claim failure')
        with self.assertLogs(level='ERROR'):
            with patch('telegram_notifications.notify_admins', new_callable=AsyncMock) as notify_admins:
                await self.notify(amount=10)
        self.journal.assert_not_awaited()
        notify_admins.assert_not_awaited()

    async def test_background_task_uses_expense_month_amount_and_is_released(self):
        with patch.object(budget_notify, 'notify_overrun', AsyncMock()) as notify:
            budget_notify.after_expense(7, 'cat_food', '2026-10-31', 'exp_test', 12.5)
            tasks = list(budget_notify._bg_tasks)
            self.assertEqual(len(tasks), 1)
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)
            notify.assert_awaited_once_with(7, 'cat_food', '2026-10', 'exp_test', 12.5)
            self.assertFalse(budget_notify._bg_tasks)


class BudgetExpenseHookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.cursor = MagicMock()
        self.cursor.execute = AsyncMock()
        self.cursor.fetchone = AsyncMock(return_value={
            'status': 'open', 'action_status': 'pending', 'user_id': 1, 'center_id': 7,
            'receipt_path': '', 'payload': json.dumps({
                'amount': 120.5, 'receipt_date': '2026-10-31',
                'expense_name': 'Тест', 'category': 'Харчування',
            }),
        })
        self.connection = MagicMock()
        self.connection.cursor.return_value.__aenter__.return_value = self.cursor
        for name in ('begin', 'commit', 'rollback'):
            setattr(self.connection, name, AsyncMock())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = self.connection
        stack.enter_context(patch.object(database, 'get_pool', AsyncMock(return_value=pool)))
        stack.enter_context(patch.object(database, 'users_cache', {'1': {'center_id': 7}}))
        stack.enter_context(patch.object(database, 'get_category_id_by_name', AsyncMock(return_value='cat_food')))
        stack.enter_context(patch.object(database, '_touch_cash_safe', AsyncMock()))
        self.after = stack.enter_context(patch.object(budget_notify, 'after_expense'))

    async def test_common_bot_and_web_save_starts_notification(self):
        expense_id = await database.add_expense(['2026-10-31', '1', 120.5, 'Тест', 'Харчування', ''])
        self.after.assert_called_once_with(7, 'cat_food', '2026-10-31', expense_id, 120.5)

    async def test_failed_insert_does_not_notify(self):
        self.cursor.execute.side_effect = RuntimeError('test insert failure')
        with self.assertRaises(RuntimeError):
            await database.add_expense(['2026-10-31', '1', 120.5, 'Тест', 'Харчування', ''])
        self.after.assert_not_called()

    async def test_notification_start_failure_does_not_undo_expense(self):
        self.after.side_effect = RuntimeError('test task failure')
        with self.assertLogs(level='ERROR'):
            expense_id = await database.add_expense(['2026-10-31', '1', 120.5, 'Тест', 'Харчування', ''])
        self.assertTrue(expense_id.startswith('exp_'))

    async def test_approval_notifies_only_after_commit(self):
        self.after.side_effect = lambda *args: self.connection.commit.assert_awaited_once()
        result = await database.decide_invalid_receipt(10, 'approved', 2)
        self.after.assert_called_once_with(7, 'cat_food', '2026-10-31', result['expense_id'], 120.5)

    async def test_rejection_does_not_notify(self):
        await database.decide_invalid_receipt(10, 'rejected', 2)
        self.after.assert_not_called()

    async def test_repeated_decision_does_not_notify(self):
        self.cursor.fetchone.return_value['status'] = 'resolved'
        self.cursor.fetchone.return_value['action_status'] = 'approved'
        result = await database.decide_invalid_receipt(10, 'approved', 2)
        self.assertTrue(result['already_decided'])
        self.after.assert_not_called()

    async def test_failed_commit_does_not_notify(self):
        self.connection.commit.side_effect = RuntimeError('test commit failure')
        with self.assertRaises(RuntimeError):
            await database.decide_invalid_receipt(10, 'approved', 2)
        self.after.assert_not_called()


if __name__ == '__main__':
    unittest.main()
