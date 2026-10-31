-- Схема бази даних MySQL для Expense Tracker (Центри Надії)
-- Кодування: utf8mb4_unicode_ci

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 1. Таблиця Центрів Надії (ЦН)
CREATE TABLE IF NOT EXISTS `centers` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(191) NOT NULL UNIQUE COMMENT 'Назва ЦН, наприклад ЦН Київ',
    `city` VARCHAR(100) NOT NULL COMMENT 'Місто розташування',
    `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 - активний, 0 - вимкнений',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Таблиця Користувачів
CREATE TABLE IF NOT EXISTS `users` (
    `telegram_id` BIGINT PRIMARY KEY COMMENT 'Telegram ID користувача',
    `name` VARCHAR(191) NOT NULL COMMENT 'Ім\'я та прізвище',
    `city` VARCHAR(100) NOT NULL COMMENT 'Місто, яке вказав користувач при реєстрації',
    `center_id` INT NULL COMMENT 'Призначений Центр Надії',
    `role` ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    `status` ENUM('pending', 'active', 'blocked') NOT NULL DEFAULT 'pending',
    `registered_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT `fk_users_center` FOREIGN KEY (`center_id`) REFERENCES `centers` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Глобальна таблиця категорій витрат
CREATE TABLE IF NOT EXISTS `categories` (
    `id` VARCHAR(50) PRIMARY KEY COMMENT 'cat_xxx або id',
    `name` VARCHAR(191) NOT NULL UNIQUE COMMENT 'Назва категорії',
    `sort_order` INT NOT NULL DEFAULT 999,
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Матриця зв\'язку: Центри Надії <-> Дозволені Категорії
CREATE TABLE IF NOT EXISTS `center_categories` (
    `center_id` INT NOT NULL,
    `category_id` VARCHAR(50) NOT NULL,
    PRIMARY KEY (`center_id`, `category_id`),
    CONSTRAINT `fk_cc_center` FOREIGN KEY (`center_id`) REFERENCES `centers` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_cc_category` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Таблиця витрат
CREATE TABLE IF NOT EXISTS `expenses` (
    `id` VARCHAR(64) PRIMARY KEY COMMENT 'Expense_ID',
    `date` DATE NOT NULL COMMENT 'Дата покупки',
    `telegram_id` BIGINT NOT NULL COMMENT 'Хто вніс витрату',
    `center_id` INT NOT NULL COMMENT 'Для якого ЦН витрата',
    `amount` DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    `expense_name` VARCHAR(255) NOT NULL COMMENT 'Опис або назва товару/чека',
    `category_id` VARCHAR(50) NOT NULL COMMENT 'Категорія витрати',
    `receipt_path` TEXT NULL COMMENT 'Посилання/шлях до фото чека',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_expenses_center` (`center_id`),
    INDEX `idx_expenses_user` (`telegram_id`),
    INDEX `idx_expenses_date` (`date`),
    CONSTRAINT `fk_expenses_user` FOREIGN KEY (`telegram_id`) REFERENCES `users` (`telegram_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT `fk_expenses_center` FOREIGN KEY (`center_id`) REFERENCES `centers` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT `fk_expenses_category` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Таблиця бюджетів (по ЦН і категоріях)
CREATE TABLE IF NOT EXISTS `budgets` (
    `id` VARCHAR(64) PRIMARY KEY COMMENT 'Budget_ID',
    `center_id` INT NOT NULL COMMENT 'ЦН',
    `category_id` VARCHAR(50) NOT NULL COMMENT 'Категорія',
    `month` VARCHAR(7) NOT NULL COMMENT 'Місяць у форматі YYYY-MM',
    `amount` DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uniq_budget` (`center_id`, `category_id`, `month`),
    CONSTRAINT `fk_budgets_center` FOREIGN KEY (`center_id`) REFERENCES `centers` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT `fk_budgets_category` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. Таблиця логів AI токенів (Gemini)
CREATE TABLE IF NOT EXISTS `api_logs` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT NOT NULL,
    `user_name` VARCHAR(191) NOT NULL,
    `input_tokens` INT NOT NULL DEFAULT 0,
    `output_tokens` INT NOT NULL DEFAULT 0,
    `estimated_cost` DECIMAL(10, 6) NOT NULL DEFAULT 0.000000,
    `model_id` VARCHAR(191) NULL COMMENT 'ID моделі OpenRouter',
    `ai_model_id` INT NULL COMMENT 'FK на ai_settings.id',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7.1. Таблиця налаштувань AI-моделей (OpenRouter)
CREATE TABLE IF NOT EXISTS `ai_settings` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(191) NOT NULL COMMENT 'Назва моделі для адміна',
    `model_id` VARCHAR(191) NOT NULL COMMENT 'ID моделі OpenRouter',
    `api_key` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'API-ключ OpenRouter',
    `is_active` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 - активна модель',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. Таблиця кодів автентифікації для веб-додатка
CREATE TABLE IF NOT EXISTS `auth_codes` (
    `code` VARCHAR(10) PRIMARY KEY COMMENT 'Одноразовий 6-значний код',
    `telegram_id` BIGINT NOT NULL,
    `expires_at` DATETIME NOT NULL,
    `is_used` TINYINT(1) NOT NULL DEFAULT 0,
    INDEX `idx_auth_tg` (`telegram_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Базові початкові категорії
INSERT IGNORE INTO `categories` (`id`, `name`, `sort_order`, `is_active`) VALUES
('cat_food', 'Продукти', 1, 1),
('cat_cafe', 'Кафе/Ресторани', 2, 1),
('cat_transport', 'Транспорт', 3, 1),
('cat_pharmacy', 'Аптека', 4, 1),
('cat_household', 'Госптовари', 5, 1),
('cat_utilities', 'Комунальні', 6, 1),
('cat_other', 'Інше', 999, 1);

SET FOREIGN_KEY_CHECKS = 1;
