#!/usr/bin/env node
/**
 * Injects updated jsCode into n8n workflow JSON files.
 * Usage: node inject-code.js <workflow-json> <node-name> <code-file>
 *
 * Or import and use programmatically.
 */
const fs = require('fs');

function injectCode(workflowPath, nodeName, newCode) {
  const wf = JSON.parse(fs.readFileSync(workflowPath, 'utf-8'));
  let found = false;
  for (const node of wf.nodes || []) {
    if (node.name === nodeName) {
      node.parameters = node.parameters || {};
      node.parameters.jsCode = newCode;
      found = true;
    }
  }
  if (!found) throw new Error(`Node "${nodeName}" not found in ${workflowPath}`);
  fs.writeFileSync(workflowPath, JSON.stringify(wf, null, 2) + '\n');
  console.log(`Injected code into "${nodeName}" in ${workflowPath}`);
}

function replaceHttpBody(workflowPath, nodeName, field, newValue) {
  const wf = JSON.parse(fs.readFileSync(workflowPath, 'utf-8'));
  let found = false;
  for (const node of wf.nodes || []) {
    if (node.name === nodeName) {
      node.parameters = node.parameters || {};
      node.parameters[field] = newValue;
      found = true;
    }
  }
  if (!found) throw new Error(`Node "${nodeName}" not found in ${workflowPath}`);
  fs.writeFileSync(workflowPath, JSON.stringify(wf, null, 2) + '\n');
  console.log(`Updated "${field}" in "${nodeName}" in ${workflowPath}`);
}

if (require.main === module) {
  const [,, wfPath, nodeName, codeFile] = process.argv;
  if (!wfPath || !nodeName || !codeFile) {
    console.error('Usage: node inject-code.js <workflow.json> <node-name> <code-file>');
    process.exit(1);
  }
  const code = fs.readFileSync(codeFile, 'utf-8');
  injectCode(wfPath, nodeName, code);
}

module.exports = { injectCode, replaceHttpBody };
