import lighthouse from 'lighthouse';
import * as chromeLauncher from 'chrome-launcher';

async function run(url) {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless=new', '--no-sandbox'] });
  try {
    const options = {
      logLevel: 'error',
      output: 'json',
      port: chrome.port,
      onlyCategories: ['performance', 'accessibility', 'best-practices', 'seo'],
    };
    const runnerResult = await lighthouse(url, options);
    process.stdout.write(runnerResult.report);
  } finally {
    await chrome.kill();
  }
}

const url = process.argv[2];
if (!url) {
  console.error('Usage: node run.mjs <url>');
  process.exit(1);
}

run(url).catch((err) => {
  console.error(err && err.message ? err.message : String(err));
  process.exit(1);
});
