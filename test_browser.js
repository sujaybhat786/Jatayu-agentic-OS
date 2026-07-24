const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch();
  const page = await browser.newPage();
  
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', error => console.log('PAGE ERROR:', error.message));

  await page.goto('http://localhost:8000', { waitUntil: 'networkidle0' });
  
  // Click chat link
  await page.click('a[href="#chat"]');
  await page.waitForTimeout(1000);
  
  await browser.close();
})();
