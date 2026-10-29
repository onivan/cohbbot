import asyncio
import aiomysql
from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

async def test_connection():
    print(f"Connecting to MySQL at {DB_HOST}:{DB_PORT}, DB={DB_NAME}, User={DB_USER}...")
    try:
        pool = await aiomysql.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            autocommit=True
        )
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SHOW TABLES;")
                tables = await cur.fetchall()
                print("Успішне підключення! Знайдені таблиці:")
                for t in tables:
                    print(f" - {list(t.values())[0]}")
                
                await cur.execute("SELECT COUNT(*) AS cnt FROM categories;")
                cat_count = await cur.fetchone()
                print(f"Кількість початкових категорій: {cat_count['cnt']}")
                
        pool.close()
        await pool.wait_closed()
        print("Всі перевірки пройдено успішно!")
    except Exception as e:
        print(f"Помилка підключення: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
