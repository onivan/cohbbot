const { test, expect } = require('@playwright/test');

const userId = process.env.E1_USER_ID;
const userCenterId = process.env.E1_USER_CENTER_ID;
const foreignCenterId = process.env.E1_FOREIGN_CENTER_ID;
const adminId = process.env.E1_ADMIN_ID;
const month = process.env.E1_MONTH;

async function openAs(page, id) {
    await page.route('https://telegram.org/**', route => route.abort());
    await page.route('https://cdn.jsdelivr.net/**', route => route.abort());
    await page.addInitScript(() => {
        window.eruda = { init() {} };
        window.Telegram = {
            WebApp: {
                ready() {},
                expand() {},
                initData: '',
                initDataUnsafe: {},
                colorScheme: 'light',
            },
        };
    });
    await page.goto(`/?user_id=${encodeURIComponent(id)}`);
    await expect(page.locator('#main-month-filter')).toBeVisible();
    if (String(id) === String(adminId)) {
        await expect(page.locator('#btn-admin-panel')).toBeVisible();
    } else {
        await expect(page.locator('#btn-expense-report')).toBeVisible();
    }
}

async function fetchReportStatus(page, centerId, reportMonth) {
    return page.evaluate(async ({ centerId, reportMonth }) => {
        const response = await fetch(
            `/api/reports/pdf?center_id=${encodeURIComponent(centerId)}&month=${encodeURIComponent(reportMonth)}`
        );
        return { status: response.status, contentType: response.headers.get('content-type') };
    }, { centerId, reportMonth });
}

test('user can download a PDF for their own center and selected month', async ({ page }) => {
    await openAs(page, userId);
    await expect(page.locator('#btn-expense-report')).toBeVisible();
    await page.locator('#main-month-filter').fill(month);

    const responsePromise = page.waitForResponse(response => response.url().includes('/api/reports/pdf'));
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#btn-expense-report').click();
    const [response, download] = await Promise.all([responsePromise, downloadPromise]);

    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toContain('application/pdf');
    expect(download.suggestedFilename()).toContain(`expense-report-${month}`);
    const body = await response.body();
    expect(body.subarray(0, 5).toString()).toBe('%PDF-');
});

test('user cannot download a report for another center', async ({ page }) => {
    await openAs(page, userId);
    const result = await fetchReportStatus(page, foreignCenterId, month);
    expect(result.status).toBe(403);
});

test('report requires a valid month', async ({ page }) => {
    await openAs(page, userId);
    const result = await fetchReportStatus(page, userCenterId, '2026-13');
    expect(result.status).toBe(400);
});

test('admin downloads a report for a selected center, not the all-centers summary', async ({ page }) => {
    await openAs(page, adminId);
    await expect(page.locator('#btn-expense-report')).toBeHidden();

    await expect(page.locator(`#main-center-filter option[value="${userCenterId}"]`)).toHaveCount(1);
    await page.locator('#main-center-filter').selectOption(String(userCenterId));
    await expect(page.locator('#btn-expense-report')).toBeVisible();
    await page.locator('#main-month-filter').fill(month);

    const responsePromise = page.waitForResponse(response => response.url().includes('/api/reports/pdf'));
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#btn-expense-report').click();
    const [response, download] = await Promise.all([responsePromise, downloadPromise]);

    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toContain('application/pdf');
    expect(download.suggestedFilename()).toContain(`center-${userCenterId}`);
});
