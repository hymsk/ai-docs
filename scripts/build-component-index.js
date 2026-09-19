#!/usr/bin/env node
/**
 * Build, validate, and query the AI Docs component reference index.
 */

const fs = require('fs');
const path = require('path');

const skillDir = path.resolve(__dirname, '..');
const componentsDir = path.join(skillDir, 'references', 'components');
const outputPath = path.join(componentsDir, 'index.json');

function fail(message) {
  throw new Error(message);
}

function parseArgs(argv) {
  const options = { check: false, query: '' };
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === '--check') {
      options.check = true;
      continue;
    }
    if (arg === '--query') {
      if (index + 1 >= argv.length) fail('--query 需要关键词。');
      options.query = argv[++index];
      continue;
    }
    if (arg.startsWith('--query=')) {
      options.query = arg.slice('--query='.length);
      if (!options.query) fail('--query 需要关键词。');
      continue;
    }
    if (arg === '-h' || arg === '--help') {
      console.log(`用法:
  node scripts/build-component-index.js
  node scripts/build-component-index.js --check
  node scripts/build-component-index.js --query "流程 分支"

默认从各组件 index.json 生成 references/components/index.json。
--check 只校验生成结果和文档路径，不写文件。
--query 按组件名称、别名、用途和关键词查询。`);
      process.exit(0);
    }
    fail(`未知选项: ${arg}`);
  }
  if (options.check && options.query) fail('--check 与 --query 不能同时使用。');
  return options;
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    fail(`${path.relative(skillDir, file)} 不是有效 JSON: ${error.message}`);
  }
}

function validateString(value, label) {
  if (typeof value !== 'string' || !value.trim()) fail(`${label} 必须是非空字符串。`);
  return value.trim();
}

function validateStringArray(value, label) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string' || !item.trim())) {
    fail(`${label} 必须是字符串数组。`);
  }
  return value.map((item) => item.trim());
}

function loadIndex() {
  const directories = fs.readdirSync(componentsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  const components = directories.map((directory) => {
    const componentDir = path.join(componentsDir, directory);
    const manifestPath = path.join(componentDir, 'index.json');
    if (!fs.existsSync(manifestPath)) fail(`组件缺少 index.json: ${path.relative(skillDir, componentDir)}`);
    const manifest = readJson(manifestPath);
    const component = validateString(manifest.component, `${directory}.component`);
    if (component !== directory) fail(`${directory}/index.json 的 component 必须等于目录名。`);
    const documents = manifest.documents;
    if (!Array.isArray(documents) || documents.length === 0) fail(`${directory}.documents 必须是非空数组。`);
    const seenPaths = new Set();
    const normalizedDocuments = documents.map((document, documentIndex) => {
      if (!document || typeof document !== 'object' || Array.isArray(document)) {
        fail(`${directory}.documents[${documentIndex}] 必须是对象。`);
      }
      const relativeDocument = validateString(document.path, `${directory}.documents[${documentIndex}].path`);
      const normalized = path.posix.normalize(relativeDocument.replace(/\\/g, '/'));
      if (normalized.startsWith('../') || normalized === '..' || path.posix.isAbsolute(normalized)) {
        fail(`${directory} 文档路径越界: ${relativeDocument}`);
      }
      if (seenPaths.has(normalized)) fail(`${directory} 文档路径重复: ${normalized}`);
      seenPaths.add(normalized);
      const absoluteDocument = path.resolve(componentDir, normalized);
      if (!absoluteDocument.startsWith(componentDir + path.sep) || !fs.statSync(absoluteDocument).isFile()) {
        fail(`${directory} 文档不存在: ${normalized}`);
      }
      return {
        path: `${directory}/${normalized}`,
        purpose: validateString(document.purpose, `${directory}.${normalized}.purpose`),
        keywords: validateStringArray(document.keywords || [], `${directory}.${normalized}.keywords`)
      };
    });
    return {
      component,
      title: validateString(manifest.title, `${directory}.title`),
      summary: validateString(manifest.summary, `${directory}.summary`),
      aliases: validateStringArray(manifest.aliases || [], `${directory}.aliases`),
      documents: normalizedDocuments
    };
  });
  return { schemaVersion: 1, generatedBy: 'scripts/build-component-index.js', components };
}

function stableJson(value) {
  return JSON.stringify(value, null, 2) + '\n';
}

function queryIndex(index, query) {
  const terms = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches = [];
  index.components.forEach((component) => {
    component.documents.forEach((document) => {
      const haystack = [component.component, component.title, component.summary]
        .concat(component.aliases, document.path, document.purpose, document.keywords)
        .join(' ')
        .toLocaleLowerCase();
      const score = terms.reduce((total, term) => total + (haystack.includes(term) ? 1 : 0), 0);
      if (score > 0) matches.push({ score, component: component.component, path: document.path, purpose: document.purpose });
    });
  });
  matches.sort((left, right) => right.score - left.score || left.path.localeCompare(right.path));
  if (matches.length === 0) {
    console.log(`没有匹配组件: ${query}`);
    return;
  }
  matches.forEach((match) => {
    console.log(`${match.score}\t${match.component}\treferences/components/${match.path}\t${match.purpose}`);
  });
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const index = loadIndex();
  const content = stableJson(index);
  if (options.query) {
    queryIndex(index, options.query);
    return;
  }
  if (options.check) {
    if (!fs.existsSync(outputPath)) fail(`总索引不存在: ${path.relative(skillDir, outputPath)}`);
    if (fs.readFileSync(outputPath, 'utf8') !== content) fail('总索引已过期，请重新生成。');
    console.log(`组件索引校验通过: ${index.components.length} 个组件。`);
    return;
  }
  fs.writeFileSync(outputPath, content, 'utf8');
  console.log(`已生成 ${path.relative(skillDir, outputPath)}: ${index.components.length} 个组件。`);
}

try {
  main();
} catch (error) {
  console.error(`错误: ${error.message}`);
  process.exit(1);
}
