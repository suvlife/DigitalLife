#!/usr/bin/env node
import fs from 'node:fs';

let failed = false;
for (const filename of process.argv.slice(2)) {
  let report;
  try {
    report = JSON.parse(fs.readFileSync(filename, 'utf8'));
  } catch (error) {
    console.error(`${filename}: invalid npm audit report: ${error.message}`);
    failed = true;
    continue;
  }
  const vulnerabilities = report.metadata?.vulnerabilities;
  if (!vulnerabilities || typeof vulnerabilities !== 'object') {
    console.error(`${filename}: missing npm audit vulnerability metadata`);
    failed = true;
    continue;
  }
  const high = Number(vulnerabilities.high || 0);
  const critical = Number(vulnerabilities.critical || 0);
  console.log(`${filename}: ${high} high, ${critical} critical production vulnerabilities`);
  if (high > 0 || critical > 0) failed = true;
}
process.exit(failed ? 1 : 0);
