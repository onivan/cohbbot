"""E1: PDF-звіт, SQL-вибірка та права на ЦН.

Запускати в staging venv після встановлення requirements.txt.
"""
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import aiomysql
from fastapi import HTTPException

import database
import report_service
import webapp


class MonthlyExpenseReportDatabaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.cursor.execute = AsyncMock()
        self.cursor.fetchone = AsyncMock(return_value={
            'id': 7, 'name': 'ЦН Київ', 'city': 'Київ',
        })
        self.cursor.fetchall = AsyncMock(return_value=[{
            'date': '2026-11-02',
            'expense_name': 'Хліб',
            'amount': Decimal('42.50'),
            'category_name': 'Харчування',
        }])
        connection = MagicMock()
        connection.cursor.return_value.__aenter__.return_value = self.cursor
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = connection
        self.get_pool = AsyncMock(return_value=pool)
        patcher = patch.object(database, 'get_pool', self.get_pool)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_report_is_scoped_to_center_and_half_open_month(self):
        result = await database.get_monthly_expense_report(7, '2026-11')
        self.assertEqual(result['center_id'], 7)
        self.assertEqual(result['center_name'], 'ЦН Київ')
        self.assertEqual(result['expenses'][0]['amount'], 42.5)
        self.assertEqual(self.cursor.execute.await_count, 2)
        sql, params = self.cursor.execute.await_args_list[1].args
        normalized = ' '.join(sql.split())
        self.assertIn('WHERE e.center_id = %s AND e.date >= %s AND e.date < %s', normalized)
        self.assertIn('LEFT JOIN categories', normalized)
        self.assertEqual(params, (7, '2026-11-01', '2026-12-01'))

    async def test_invalid_month_is_rejected_before_database_access(self):
        for month in ('', '2026-00', '2026-13', '2026-1', 'nope'):
            with self.subTest(month=month):
                with self.assertRaises(ValueError):
                    await database.get_monthly_expense_report(7, month)
        self.get_pool.assert_not_awaited()

    async def test_missing_center_returns_none_without_expense_query(self):
        self.cursor.fetchone.return_value = None
        result = await database.get_monthly_expense_report(999, '2026-11')
        self.assertIsNone(result)
        self.assertEqual(self.cursor.execute.await_count, 1)


class MonthlyExpenseReportDatabaseIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        pool = database._pool
        if pool is not None:
            pool.close()
            await pool.wait_closed()
            database._pool = None

    async def test_existing_center_report_query_reads_without_mutation(self):
        pool = await database.get_pool()
        async with pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT id FROM centers ORDER BY id LIMIT 1")
                row = await cursor.fetchone()
        if not row:
            self.skipTest('У staging БД немає Центрів Надії')

        report = await database.get_monthly_expense_report(
            int(row[0]), database.current_month()
        )
        self.assertEqual(report['center_id'], int(row[0]))
        self.assertEqual(report['month'], database.current_month())
        self.assertIsInstance(report['expenses'], list)
        self.assertTrue(all('receipt_path' not in item for item in report['expenses']))


class MonthlyExpensePdfTests(unittest.TestCase):
    def test_summary_totals_match_rows_and_category_groups(self):
        rows, total, by_category = report_service.summarize_expenses([
            {'category_name': 'Харчування', 'amount': '42.50'},
            {'category_name': 'Харчування', 'amount': 7.5},
            {'category_name': 'Транспорт', 'amount': 10},
        ])
        self.assertEqual(total, Decimal('60.00'))
        self.assertEqual(by_category, {
            'Харчування': Decimal('50.00'),
            'Транспорт': Decimal('10.00'),
        })
        self.assertEqual(len(rows), 3)
        self.assertEqual(report_service._format_money(total), '60,00 грн')

    def test_generates_pdf_with_unicode_and_does_not_mutate_source(self):
        expense = {
            'date': '2026-11-02', 'expense_name': 'Хліб <свіжий>',
            'category_name': 'Харчування', 'amount': 42.5,
        }
        report = {
            'center_id': 7, 'center_name': 'ЦН Київ', 'city': 'Київ',
            'month': '2026-11', 'expenses': [expense],
        }
        pdf = report_service.build_monthly_expense_pdf(report)
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertGreater(len(pdf), 1000)
        self.assertNotIn('_amount_decimal', expense)

    def test_empty_month_still_generates_a_pdf(self):
        pdf = report_service.build_monthly_expense_pdf({
            'center_id': 7, 'center_name': 'ЦН Київ', 'month': '2026-11', 'expenses': [],
        })
        self.assertTrue(pdf.startswith(b'%PDF-'))

    def test_invalid_report_data_is_rejected(self):
        with self.assertRaises(ValueError):
            report_service.build_monthly_expense_pdf({
                'center_id': 7, 'center_name': 'ЦН Київ', 'month': '2026-13', 'expenses': [],
            })
        with self.assertRaises(ValueError):
            report_service.build_monthly_expense_pdf({
                'center_id': 7, 'center_name': 'ЦН Київ', 'month': '2026-11',
                'expenses': [{'amount': 'NaN'}],
            })


class MonthlyExpenseReportEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_response_and_access_scope(self):
        report_data = {
            'center_id': 8, 'center_name': 'ЦН Львів', 'month': '2026-11', 'expenses': [],
        }
        with patch.object(webapp, '_cash_center_for', AsyncMock(return_value=8)) as scope, \
             patch.object(database, 'get_monthly_expense_report', AsyncMock(return_value=report_data)), \
             patch.object(report_service, 'build_monthly_expense_pdf', return_value=b'%PDF-test'):
            response = await webapp.monthly_expense_report_pdf(8, '2026-11', current_user=12)

        scope.assert_awaited_once_with(12, 8)
        self.assertEqual(response.media_type, 'application/pdf')
        self.assertEqual(response.body, b'%PDF-test')
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertEqual(response.headers['cache-control'], 'no-store')

    async def test_month_is_required_and_validated(self):
        with patch.object(webapp, '_cash_center_for', AsyncMock(return_value=8)):
            for month in (None, '2026-13'):
                with self.subTest(month=month):
                    with self.assertRaises(HTTPException) as error:
                        await webapp.monthly_expense_report_pdf(8, month, current_user=12)
                    self.assertEqual(error.exception.status_code, 400)

    async def test_non_admin_cannot_select_foreign_center(self):
        with patch.dict(database.users_cache, {'12': {'center_id': 7, 'role': 'user'}}):
            with self.assertRaises(HTTPException) as error:
                await webapp._cash_center_for(12, 8)
        self.assertEqual(error.exception.status_code, 403)

    async def test_admin_can_select_another_center(self):
        with patch.dict(database.users_cache, {'12': {'center_id': 7, 'role': 'admin'}}):
            self.assertEqual(await webapp._cash_center_for(12, 8), 8)


if __name__ == '__main__':
    unittest.main()
