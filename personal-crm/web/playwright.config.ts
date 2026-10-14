import { defineConfig, devices } from '@playwright/test';
export default defineConfig({testDir:'./e2e',workers:1,fullyParallel:false,timeout:30000,
  use:{baseURL:process.env.CRM_WEB_TEST_BASE || 'http://127.0.0.1:8001/app/',trace:'retain-on-failure'},
  projects:[{name:'desktop',use:{viewport:{width:1440,height:1000}}},{name:'mobile',use:{...devices['iPhone 13'],defaultBrowserType:'chromium'}}],
});
