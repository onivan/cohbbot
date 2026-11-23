"""B5: user bug reports, admin recipient settings, and best-effort Telegram delivery."""
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import database
import webapp
from fastapi import HTTPException


class BugReportTelegramIdTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.cursor = MagicMock()
        self.cursor.execute = AsyncMock()
        connection = MagicMock()
        connection.cursor.return_value.__aenter__.return_value = self.cursor
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = connection
        self.get_pool = AsyncMock(return_value=pool)
        stack.enter_context(patch.object(database, 'get_pool', self.get_pool))

    def test_id_normalization_and_disable_value(self):
        self.assertEqual(database.validate_bug_report_telegram_id(' 0012345 '), '12345')
        self.assertEqual(database.validate_bug_report_telegram_id(None), '')
        self.assertEqual(database.validate_bug_report_telegram_id('  '), '')

    def test_invalid_ids_are_rejected(self):
        for value in ('@developer', '-100123', '１２３', '0', '9223372036854775808'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    database.validate_bug_report_telegram_id(value)
        self.get_pool.assert_not_awaited()

    async def test_get_setting_returns_none_when_missing(self):
        self.cursor.fetchone = AsyncMock(return_value=None)
        self.assertIsNone(await database.get_bug_report_telegram_id())
        self.cursor.execute.assert_awaited_once_with(
            'SELECT `value` FROM app_settings WHERE `key` = %s',
            ('bug_report_telegram_id',),
        )

    async def test_get_setting_normalizes_saved_id(self):
        self.cursor.fetchone = AsyncMock(return_value=('0012345',))
        self.assertEqual(await database.get_bug_report_telegram_id(), '12345')

    async def test_invalid_saved_id_is_ignored(self):
        self.cursor.fetchone = AsyncMock(return_value=('@developer',))
        with self.assertLogs(level='ERROR'):
            self.assertIsNone(await database.get_bug_report_telegram_id())

    async def test_save_setting_upserts_and_can_be_cleared(self):
        self.assertEqual(await database.set_bug_report_telegram_id('123456'), '123456')
        sql, params = self.cursor.execute.await_args.args
        self.assertIn('INSERT INTO app_settings', sql)
        self.assertIn('ON DUPLICATE KEY UPDATE', sql)
        self.assertEqual(params, ('bug_report_telegram_id', '123456'))

        self.cursor.execute.reset_mock()
        self.assertIsNone(await database.set_bug_report_telegram_id(''))
        self.assertEqual(self.cursor.execute.await_args.args[1], ('bug_report_telegram_id', ''))


class BugReportEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_is_journaled_and_sent_as_plain_text(self):
        request = MagicMock()
        sent_message = MagicMock(message_id=45)
        with patch.dict(database.users_cache, {'17': {
                'name': 'Учасник', 'center': 'ЦН Львів', 'center_id': 3,
        }}), \
             patch.object(database, 'create_admin_notification', AsyncMock(return_value=91)) as create, \
             patch.object(database, 'get_bug_report_telegram_id', AsyncMock(return_value='999')) as get_id, \
             patch.object(webapp.bot, 'send_message', AsyncMock(return_value=sent_message)) as send, \
             patch.object(database, 'save_admin_notification_messages', AsyncMock(return_value=True)) as save:
            result = await webapp.submit_bug_report(
                webapp.BugReportData(
                    title='Не відкривається бюджет',
                    description='При натисканні на ліміти сторінка зависає.',
                    page='/?view=limits',
                ),
                request,
                current_user=17,
            )

        self.assertEqual(result['delivery_status'], 'sent')
        self.assertEqual(result['notification_id'], 91)
        create.assert_awaited_once()
        notification = create.await_args.kwargs
        self.assertEqual(notification['type'], 'bug_report')
        self.assertEqual(notification['center_id'], 3)
        self.assertEqual(notification['user_id'], 17)
        self.assertEqual(notification['payload']['page'], '/?view=limits')
        self.assertEqual(notification['action_status'], 'resolved')
        get_id.assert_awaited_once()
        message = send.await_args.args[1]
        self.assertIn('Користувач: Учасник (ID 17)', message)
        self.assertIn('ЦН: ЦН Львів', message)
        self.assertIn('Сторінка: /?view=limits', message)
        self.assertIn('При натисканні на ліміти сторінка зависає.', message)
        self.assertNotIn('parse_mode', send.await_args.kwargs)
        save.assert_awaited_once_with(91, [{
            'chat_id': 999, 'message_id': 45, 'kind': 'text',
        }])

    async def test_report_is_kept_when_telegram_delivery_fails(self):
        with patch.dict(database.users_cache, {}, clear=True), \
             patch.object(database, 'get_user_center_id', AsyncMock(return_value=None)), \
             patch.object(database, 'create_admin_notification', AsyncMock(return_value=92)) as create, \
             patch.object(database, 'get_bug_report_telegram_id', AsyncMock(return_value='999')), \
             patch.object(webapp.bot, 'send_message', AsyncMock(side_effect=RuntimeError('bot blocked'))):
            with self.assertLogs(level='ERROR'):
                result = await webapp.submit_bug_report(
                    webapp.BugReportData(description='The page fails to load after I sign in.'),
                    MagicMock(),
                    current_user=18,
                )

        self.assertEqual(result['delivery_status'], 'failed')
        create.assert_awaited_once()

    async def test_unconfigured_destination_keeps_report_in_journal(self):
        with (
            patch.object(database, 'create_admin_notification', AsyncMock(return_value=93)) as create,
            patch.object(database, 'get_user_center_id', AsyncMock(return_value=None)),
            patch.object(database, 'get_bug_report_telegram_id', AsyncMock(return_value=None)),
            patch.object(webapp.bot, 'send_message', AsyncMock()) as send,
        ):
            result = await webapp.submit_bug_report(
                webapp.BugReportData(description='A sufficiently long report description.'),
                MagicMock(),
                current_user=19,
            )

        self.assertEqual(result['delivery_status'], 'not_configured')
        create.assert_awaited_once()
        send.assert_not_awaited()

    @patch.object(database, 'get_user_center_id', new_callable=AsyncMock, return_value=None)
    async def test_report_validates_text_and_sanitizes_external_page(self, _get_center):
        with patch.object(database, 'create_admin_notification', AsyncMock(return_value=94)) as create, \
             patch.object(database, 'get_bug_report_telegram_id', AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as error:
                await webapp.submit_bug_report(
                    webapp.BugReportData(
                        title='x' * 121,
                        description='This description is long enough to be accepted.',
                        page='/safe',
                    ),
                    MagicMock(),
                    current_user=20,
                )
            self.assertEqual(error.exception.status_code, 400)
            create.assert_not_awaited()

            result = await webapp.submit_bug_report(
                webapp.BugReportData(
                    description='This description is long enough to be accepted.',
                    page='//example.com/phishing',
                ),
                MagicMock(),
                current_user=20,
            )
        self.assertEqual(result['delivery_status'], 'not_configured')
        self.assertEqual(create.await_args.kwargs['payload']['page'], '/')

    async def test_recipient_setting_endpoints_require_admin(self):
        with patch.object(database, 'is_admin', return_value=False), \
             patch.object(database, 'get_bug_report_telegram_id', AsyncMock()) as get_id:
            with self.assertRaises(HTTPException) as error:
                await webapp.admin_get_bug_report_telegram_id(current_user=100)
        self.assertEqual(error.exception.status_code, 403)
        get_id.assert_not_awaited()

    async def test_admin_can_read_and_update_recipient_setting(self):
        with patch.object(database, 'is_admin', return_value=True), \
             patch.object(database, 'get_bug_report_telegram_id', AsyncMock(return_value='123')) as get_id:
            result = await webapp.admin_get_bug_report_telegram_id(current_user=100)
        self.assertEqual(result['telegram_user_id'], '123')
        get_id.assert_awaited_once()

        with patch.object(database, 'is_admin', return_value=True), \
             patch.object(database, 'set_bug_report_telegram_id', AsyncMock(return_value=None)) as set_id:
            result = await webapp.admin_set_bug_report_telegram_id(
                webapp.BugReportRecipientData(telegram_user_id=None), current_user=100
            )
        self.assertIsNone(result['telegram_user_id'])
        set_id.assert_awaited_once_with(None)


if __name__ == '__main__':
    unittest.main()
