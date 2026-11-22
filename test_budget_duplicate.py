"""C1: пошук схожих витрат. Запуск: python -m unittest test_budget_duplicate."""
import hashlib
import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import aiomysql
import database


class FindDuplicateExpenseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.cursor.execute = AsyncMock()
        self.cursor.fetchall = AsyncMock(return_value=[])
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

    async def test_receipt_hash_match_is_center_scoped_and_ignores_ai_fields(self):
        receipt_hash = 'a' * 64
        result = await database.find_duplicate_expense(
            7, '2026-11-21', 99.0, 'cat_other', 'Інша AI-назва',
            receipt_hash=receipt_hash,
        )
        self.assertEqual(result['expense_id'], 'exp_existing')
        sql, params = self.cursor.execute.call_args.args
        self.assertIn('center_id = %s AND receipt_sha256 = %s', ' '.join(sql.split()))
        self.assertEqual(params, (7, receipt_hash))

    async def test_pre_ai_hash_lookup_checks_only_center_and_content_hash(self):
        receipt_hash = 'c' * 64
        result = await database.find_duplicate_receipt_hash(7, receipt_hash)
        self.assertEqual(result['expense_id'], 'exp_existing')
        sql, params = self.cursor.execute.call_args.args
        self.assertIn('center_id = %s AND receipt_sha256 = %s', ' '.join(sql.split()))
        self.assertEqual(params, (7, receipt_hash))

    async def test_legacy_same_amount_candidate_is_hashed_and_matched(self):
        self.cursor.fetchone.side_effect = [None]
        self.cursor.fetchall.return_value = [{
            'id': 'exp_legacy', 'telegram_id': 13, 'date': '2026-11-01',
            'amount': Decimal('42.50'), 'expense_name': 'Old AI label',
            'category_id': 'cat_food', 'receipt_path': '/receipts/13/old.jpg',
        }]
        candidate_hash = 'b' * 64
        with patch.object(database, 'receipt_sha256', AsyncMock(return_value=candidate_hash)) as hash_file:
            result = await database.find_duplicate_expense(
                7, '2026-11-20', 42.5, 'cat_food', 'New AI label',
                receipt_hash=candidate_hash,
            )

        self.assertEqual(result['expense_id'], 'exp_legacy')
        hash_file.assert_awaited_once_with(13, '/receipts/13/old.jpg')
        update_sql, update_params = self.cursor.execute.call_args.args
        self.assertIn('UPDATE expenses SET receipt_sha256', update_sql)
        self.assertEqual(update_params, (candidate_hash, 'exp_legacy'))

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

    async def test_invalid_or_non_finite_amount_does_not_query_without_hash(self):
        for amount in ('invalid', float('nan'), float('inf')):
            with self.subTest(amount=amount):
                self.assertIsNone(await database.find_duplicate_expense(
                    7, '2026-11-20', amount, 'cat_food', 'Магазин'
                ))
        self.get_pool.assert_not_awaited()

    async def test_invalid_receipt_path_is_not_hashed(self):
        self.assertIsNone(await database.receipt_sha256(
            7, 'https://example.test/receipts/8/another-users-file.jpg'
        ))

    def test_sha256_file_reads_exact_bytes(self):
        content = b'receipt image bytes'
        with tempfile.NamedTemporaryFile(delete=False) as receipt:
            receipt.write(content)
            path = receipt.name
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self.assertEqual(database._sha256_file(path), hashlib.sha256(content).hexdigest())

    async def test_schema_adds_nullable_hash_and_search_indexes(self):
        await database.ensure_duplicate_expense_schema()
        statements = [' '.join(call.args[0].split())
                      for call in self.cursor.execute.await_args_list]
        self.assertTrue(any('ADD COLUMN `receipt_sha256` CHAR(64) NULL' in sql
                            for sql in statements))
        self.assertTrue(any('idx_expenses_center_receipt_hash' in sql for sql in statements))
        self.assertTrue(any('idx_expenses_center_amount' in sql for sql in statements))


class ReceiptHashPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_expense_persists_normalized_receipt_hash(self):
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        connection = MagicMock()
        connection.cursor.return_value.__aenter__.return_value = cursor
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = connection
        receipt_hash = 'A' * 64

        with patch.object(database, 'get_pool', AsyncMock(return_value=pool)), \
             patch.object(database, 'users_cache', {'1': {'center_id': 7}}), \
             patch.object(database, 'get_category_id_by_name', AsyncMock(return_value='cat_food')), \
             patch.object(database, 'receipt_sha256', AsyncMock(return_value=receipt_hash)), \
             patch.object(database, '_touch_cash_safe', AsyncMock()), \
             patch.object(database, '_notify_budget_safe'):
            await database.add_expense(
                ['2026-11-20', '1', 42.5, 'Магазин', 'cat_food', '/receipts/1/receipt.jpg']
            )

        sql, params = cursor.execute.call_args.args
        self.assertIn('receipt_sha256', sql)
        self.assertEqual(params[-1], receipt_hash.lower())


if __name__ == '__main__':
    unittest.main()
