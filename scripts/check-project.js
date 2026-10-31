import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
const config = JSON.parse(await readFile('vercel.json', 'utf8'));
if (config.functions?.['api/ff/*.js']?.maxDuration !== 90) throw new Error('Incorrect Vercel function configuration');
for (const file of ['server.js', 'lib/forward.js', 'lib/send.js', 'api/health.js', 'api/ff/[uid].js']) execFileSync(process.execPath, ['--check', file]);
console.log('Gateway syntax and Vercel configuration checked.');
