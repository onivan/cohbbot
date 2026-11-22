const { defineConfig } = require('@playwright/test');

const requiredEnv = [
    'E1_STAGING_URL',
    'E1_USER_ID',
    'E1_USER_CENTER_ID',
    'E1_FOREIGN_CENTER_ID',
    'E1_ADMIN_ID',
    'E1_MONTH',
];
const missingEnv = requiredEnv.filter(name => !process.env[name]);
if (missingEnv.length) {
    throw new Error(`Set browser-test environment variables: ${missingEnv.join(', ')}`);
}
if (!/^https?:\/\//.test(process.env.E1_STAGING_URL)) {
    throw new Error('E1_STAGING_URL must be an HTTP(S) URL');
}
for (const name of ['E1_USER_ID', 'E1_USER_CENTER_ID', 'E1_FOREIGN_CENTER_ID', 'E1_ADMIN_ID']) {
    if (!/^\d+$/.test(process.env[name])) {
        throw new Error(`${name} must be a numeric staging identifier`);
    }
}
if (process.env.E1_USER_CENTER_ID === process.env.E1_FOREIGN_CENTER_ID) {
    throw new Error('E1_FOREIGN_CENTER_ID must differ from E1_USER_CENTER_ID');
}
if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(process.env.E1_MONTH)) {
    throw new Error('E1_MONTH must use YYYY-MM');
}

module.exports = defineConfig({
    testDir: '.',
    testMatch: '**/*.spec.js',
    fullyParallel: false,
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 1 : 0,
    reporter: 'list',
    use: {
        baseURL: process.env.E1_STAGING_URL.replace(/\/$/, ''),
        browserName: 'chromium',
        headless: true,
        acceptDownloads: true,
        viewport: { width: 1280, height: 900 },
        trace: 'retain-on-failure',
    },
});
