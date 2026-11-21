"""B1: підрахунок витрат категорії. Запуск на VPS: python -m unittest test_budget_spent.

Модульні тести підміняють пул; інтеграційні лише читають наявну БД.
"""
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import aiomysql
import database


class CategorySpentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.cursor.execute = AsyncMock()
        self.cursor.fetchone = AsyncMock(return_value={'spent': Decimal('123.45')})
        connection = MagicMock()
        connection.cursor.return_value.__aenter__.return_value = self.cursor
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = connection
        self.get_pool = AsyncMock(return_value=pool)
        patcher = patch.object(database, 'get_pool', self.get_pool)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_total_and_scope(self):
        result = await database.get_category_spent(7, 'cat_food', '2026-11')
        self.assertEqual(result, 123.45)
        self.assertIsInstance(result, float)
        self.cursor.execute.assert_awaited_once()
        sql, params = self.cursor.execute.call_args.args
        sql = ' '.join(sql.split())
        self.assertIn('COALESCE(SUM(amount), 0)', sql)
        self.assertIn('center_id = %s AND category_id = %s', sql)
        self.assertIn('date >= %s AND date < %s', sql)
        self.assertEqual(params, (7, 'cat_food', '2026-11-01', '2026-12-01'))

    async def test_empty_total(self):
        self.cursor.fetchone.return_value = {'spent': Decimal('0.00')}
        self.assertEqual(await database.get_category_spent(7, 'cat_food', '2026-11'), 0.0)

    async def test_leap_february_bounds(self):
        await database.get_category_spent(7, 'cat_food', '2024-02')
        self.assertEqual(self.cursor.execute.call_args.args[1][2:],
                         ('2024-02-01', '2024-03-01'))

    async def test_december_bounds(self):
        await database.get_category_spent(7, 'cat_food', '2026-12')
        self.assertEqual(self.cursor.execute.call_args.args[1][2:],
                         ('2026-12-01', '2027-01-01'))

    async def test_invalid_month_does_not_query_database(self):
        for month in ('', None, '2026-00', '2026-13', '2026-1', 'not-a-month'):
            with self.subTest(month=month):
                with self.assertRaises(ValueError):
                    await database.get_category_spent(7, 'cat_food', month)
        self.get_pool.assert_not_awaited()

    async def test_database_errors_propagate(self):
        self.cursor.execute.side_effect = RuntimeError('test database error')
        with self.assertRaises(RuntimeError):
            await database.get_category_spent(7, 'cat_food', '2026-11')


class CategorySpentDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        pool = database._pool
        if pool is not None:
            pool.close()
            await pool.wait_closed()
            database._pool = None

    async def test_existing_totals_match_independent_grouping(self):
        pool = await database.get_pool()
        async with pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("""
                    SELECT center_id, category_id,
                           DATE_FORMAT(date, '%Y-%m') AS expense_month,
                           SUM(amount) AS spent
                    FROM expenses
                    GROUP BY center_id, category_id, DATE_FORMAT(date, '%Y-%m')
                """)
                rows = await cursor.fetchall()
        if not rows:
            self.skipTest('У БД немає витрат для звірки')
        for row in rows:
            with self.subTest(center=row['center_id'], category=row['category_id'],
                              month=row['expense_month']):
                result = await database.get_category_spent(
                    row['center_id'], row['category_id'], row['expense_month'])
                self.assertEqual(result, float(row['spent']))

    async def test_center_without_expenses_returns_zero(self):
        pool = await database.get_pool()
        async with pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM centers')
                center_id = (await cursor.fetchone())[0]
        result = await database.get_category_spent(center_id, 'cat_food', '2026-11')
        self.assertEqual(result, 0.0)


if __name__ == '__main__':
    unittest.main()
