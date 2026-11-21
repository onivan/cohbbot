"""C1: пошук схожих витрат. Запуск: python -m unittest test_budget_duplicate."""
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import aiomysql
import database


class FindDuplicateExpenseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.cursor.execute = AsyncMock()
        self.cursor.fetchone = AsyncMock(return_value={
            'id': 'exp_existing',
            'date': '2026-11-20',
            'amount': Decimal('42.50'),
            'expense_name': 'Магазин',
            'category_id': 'cat_food',
        })
        connection = MagicMock()
        connection.cursor.return_value.__aenter__.return_value = self.cursor
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = connection
        self.get_pool = AsyncMock(return_value=pool)
        patcher = patch.object(database, 'get_pool', self.get_pool)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_returns_match_scoped_to_center_and_all_fields(self):
        result = await database.find_duplicate_expense(
            7, '2026-11-20 12:00:00', 42.5, 'cat_food', ' Магазин '
        )
        self.assertEqual(result, {
            'expense_id': 'exp_existing',
            'date': '2026-11-20',
            'amount': 42.5,
            'expense_name': 'Магазин',
            'category_id': 'cat_food',
        })
        sql, params = self.cursor.execute.call_args.args
        sql = ' '.join(sql.split())
        self.assertIn('center_id = %s AND date = %s AND amount = %s', sql)
        self.assertIn('category_id = %s', sql)
        self.assertIn('LOWER(TRIM(expense_name)) = LOWER(TRIM(%s))', sql)
        self.assertEqual(params, (7, '2026-11-20', 42.5, 'cat_food', 'Магазин'))

    async def test_no_match_returns_none(self):
        self.cursor.fetchone.return_value = None
        self.assertIsNone(await database.find_duplicate_expense(
            8, '2026-11-20', 42.5, 'cat_food', 'Магазин'
        ))

    async def test_missing_match_fields_do_not_query(self):
        for fields in (
            (None, '2026-11-20', 42.5, 'cat_food', 'Магазин'),
            (7, '', 42.5, 'cat_food', 'Магазин'),
            (7, '2026-11-20', 42.5, '', 'Магазин'),
            (7, '2026-11-20', 42.5, 'cat_food', '  '),
        ):
            with self.subTest(fields=fields):
                self.assertIsNone(await database.find_duplicate_expense(*fields))
        self.get_pool.assert_not_awaited()

    async def test_invalid_or_non_finite_amount_does_not_query(self):
        for amount in ('invalid', float('nan'), float('inf')):
            with self.subTest(amount=amount):
                self.assertIsNone(await database.find_duplicate_expense(
                    7, '2026-11-20', amount, 'cat_food', 'Магазин'
                ))
        self.get_pool.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
