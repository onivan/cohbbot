import asyncio
import gspread
from google.oauth2.service_account import Credentials
import aiomysql
from config import SPREADSHEET_ID, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

async def migrate_users():
    print("1. Зчитування користувачів з Google Sheets...")
    try:
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        users_sheet = sh.worksheet("Users")
        records = users_sheet.get_all_records()
        print(f"Знайдено записів у Google Sheets: {len(records)}")
    except Exception as e:
        print(f"Помилка доступу до Google Sheets: {e}")
        return

    print("2. Підключення до MySQL...")
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
            # 1. Створюємо центри, якщо вони згадуються у користувачів
            centers_map = {} # name -> id
            await cur.execute("SELECT id, name FROM centers;")
            for row in await cur.fetchall():
                centers_map[row['name'].strip().lower()] = row['id']

            imported_users = 0
            for r in records:
                tg_id_raw = r.get('Telegram_ID')
                if not tg_id_raw:
                    continue
                try:
                    tg_id = int(str(tg_id_raw).strip())
                except ValueError:
                    continue

                name = str(r.get('Name', 'Користувач')).strip()
                center_name = str(r.get('Center', '')).strip()
                role = str(r.get('Role', 'user')).strip().lower()
                if role not in ('user', 'admin'):
                    role = 'user'

                # Створюємо/знаходимо центр
                center_id = None
                if center_name:
                    c_key = center_name.lower()
                    if c_key in centers_map:
                        center_id = centers_map[c_key]
                    else:
                        city = center_name.replace("ЦН", "").replace("цн", "").strip() or "Україна"
                        await cur.execute(
                            "INSERT INTO centers (name, city, is_active) VALUES (%s, %s, 1);",
                            (center_name, city)
                        )
                        center_id = cur.lastrowid
                        centers_map[c_key] = center_id
                        print(f" [+] Створено центр: {center_name} (ID: {center_id})")

                # Додаємо користувача (зі статусом active для існуючих)
                # Якщо користувач вже є, оновлюємо
                city = center_name.replace("ЦН", "").replace("цн", "").strip() or "Україна"
                sql = """
                    INSERT INTO users (telegram_id, name, city, center_id, role, status)
                    VALUES (%s, %s, %s, %s, %s, 'active')
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        center_id = VALUES(center_id),
                        role = VALUES(role),
                        status = 'active';
                """
                await cur.execute(sql, (tg_id, name, city, center_id, role))
                imported_users += 1
                print(f" -> Користувач {name} (ID: {tg_id}, роль: {role}, ЦН: {center_name})")

            print(f"\nУспішно перенесено {imported_users} користувачів у MySQL!")

    pool.close()
    await pool.wait_closed()

if __name__ == "__main__":
    asyncio.run(migrate_users())
