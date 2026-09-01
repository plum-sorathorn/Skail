/**
 * AutoConduck OMA Sidecar Workspace Tool Suite
 * Pure Node.js (>=18) implementation of workspace-bounded agent tools.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

/**
 * Resolves targetPath relative to workspaceRoot and verifies it is inside the workspace boundary.
 * Throws an error if security bound is violated.
 */
function resolveWorkspacePath(workspaceRoot, targetPath) {
  const root = path.resolve(workspaceRoot || process.cwd());
  const target = path.resolve(root, targetPath || '.');

  const rel = path.relative(root, target);
  const isSubdir = !rel.startsWith('..') && !path.isAbsolute(rel);

  if (!isSubdir && target !== root) {
    throw new Error(`Security Violation: Path '${targetPath}' is outside workspace root '${root}'`);
  }
  return target;
}

/**
 * Tool: read
 * Read file contents bounded by workspace root.
 */
async function readTool({ path: filePath, start_line, end_line, startLine, endLine }, workspaceRoot) {
  if (!filePath) throw new Error("Parameter 'path' is required for read tool");
  const target = resolveWorkspacePath(workspaceRoot, filePath);
  if (!fs.existsSync(target)) {
    throw new Error(`File not found: ${filePath}`);
  }
  const stat = fs.statSync(target);
  if (stat.isDirectory()) {
    throw new Error(`Path is a directory, not a file: ${filePath}`);
  }

  const content = fs.readFileSync(target, 'utf8');
  const sLine = start_line ?? startLine;
  const eLine = end_line ?? endLine;
  const relPath = path.relative(workspaceRoot || process.cwd(), target).replace(/\\/g, '/');

  if (sLine !== undefined || eLine !== undefined) {
    const lines = content.split(/\r?\n/);
    const start = Math.max(1, sLine || 1) - 1;
    const end = Math.min(lines.length, eLine || lines.length);
    const sliced = lines.slice(start, end).join('\n');
    return {
      status: 'success',
      path: relPath,
      totalLines: lines.length,
      startLine: start + 1,
      endLine: end,
      content: sliced
    };
  }

  return {
    status: 'success',
    path: relPath,
    size: stat.size,
    content: content
  };
}

/**
 * Tool: write
 * Write file contents inside workspace root. Creates parent directories if missing.
 */
async function writeTool({ path: filePath, content }, workspaceRoot) {
  if (!filePath) throw new Error("Parameter 'path' is required for write tool");
  const target = resolveWorkspacePath(workspaceRoot, filePath);
  const dir = path.dirname(target);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const fileContent = typeof content === 'string' ? content : String(content ?? '');
  fs.writeFileSync(target, fileContent, 'utf8');
  const relPath = path.relative(workspaceRoot || process.cwd(), target).replace(/\\/g, '/');

  return {
    status: 'success',
    path: relPath,
    bytesWritten: Buffer.byteLength(fileContent, 'utf8')
  };
}

/**
 * Tool: edit
 * Replace target string with replacement string in a workspace file.
 */
async function editTool(args, workspaceRoot) {
  const filePath = args.path;
  if (!filePath) throw new Error("Parameter 'path' is required for edit tool");
  const targetFile = resolveWorkspacePath(workspaceRoot, filePath);
  if (!fs.existsSync(targetFile)) {
    throw new Error(`File not found: ${filePath}`);
  }

  const findStr = args.target ?? args.target_string ?? args.old_string;
  const replaceStr = args.replacement ?? args.replacement_string ?? args.new_string;

  if (findStr === undefined || replaceStr === undefined) {
    throw new Error("Missing required 'target' or 'replacement' parameters for edit tool");
  }

  const content = fs.readFileSync(targetFile, 'utf8');
  if (!content.includes(findStr)) {
    throw new Error(`Target string not found in file '${filePath}'`);
  }

  const updated = content.replace(findStr, replaceStr);
  fs.writeFileSync(targetFile, updated, 'utf8');
  const relPath = path.relative(workspaceRoot || process.cwd(), targetFile).replace(/\\/g, '/');

  return {
    status: 'success',
    path: relPath,
    replaced: true
  };
}

/**
 * Tool: grep
 * Search workspace files using regex or literal substring.
 */
async function grepTool({ query, path: searchPath = '.', dir, is_regex = false, isRegex = false }, workspaceRoot) {
  if (!query) throw new Error("Parameter 'query' is required for grep tool");
  const root = workspaceRoot || process.cwd();
  const targetDir = resolveWorkspacePath(root, searchPath || dir || '.');
  const useRegex = Boolean(is_regex || isRegex);
  let regex = null;
  if (useRegex) {
    regex = new RegExp(query, 'g');
  }

  const results = [];
  const maxMatches = 100;
  const ignoreDirs = new Set(['node_modules', '.git', '__pycache__', '.venv', 'dist', 'build', '.gemini']);

  function walk(currentDir) {
    if (results.length >= maxMatches) return;
    let entries;
    try {
      entries = fs.readdirSync(currentDir, { withFileTypes: true });
    } catch (e) {
      return;
    }

    for (const entry of entries) {
      if (results.length >= maxMatches) break;
      const fullPath = path.join(currentDir, entry.name);

      if (entry.isDirectory()) {
        if (!ignoreDirs.has(entry.name)) {
          walk(fullPath);
        }
      } else if (entry.isFile()) {
        try {
          const stat = fs.statSync(fullPath);
          if (stat.size > 2 * 1024 * 1024) continue; // skip large files > 2MB

          const fileContent = fs.readFileSync(fullPath, 'utf8');
          const lines = fileContent.split(/\r?\n/);

          for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            let matched = false;
            if (useRegex) {
              regex.lastIndex = 0;
              matched = regex.test(line);
            } else {
              matched = line.includes(query);
            }

            if (matched) {
              const rel = path.relative(root, fullPath).replace(/\\/g, '/');
              results.push({
                file: rel,
                line: i + 1,
                content: line.trim()
              });
              if (results.length >= maxMatches) break;
            }
          }
        } catch (err) {
          // ignore unreadable/binary files
        }
      }
    }
  }

  walk(targetDir);

  return {
    status: 'success',
    query,
    matchCount: results.length,
    matches: results
  };
}

/**
 * Tool: glob
 * Find matching file paths in workspace using glob pattern.
 */
async function globTool({ pattern, path: searchPath = '.', dir }, workspaceRoot) {
  if (!pattern) throw new Error("Parameter 'pattern' is required for glob tool");
  const root = workspaceRoot || process.cwd();
  const targetDir = resolveWorkspacePath(root, searchPath || dir || '.');
  const results = [];
  const maxResults = 200;
  const ignoreDirs = new Set(['node_modules', '.git', '__pycache__', '.venv', 'dist', 'build']);

  function convertGlobToRegex(p) {
    const norm = p.replace(/\\/g, '/');
    const regStr = norm
      .replace(/\./g, '\\.')
      .replace(/\*\*/g, '.*')
      .replace(/(?<!\.)\*/g, '[^/]*')
      .replace(/\?/g, '.');
    return new RegExp(`^${regStr}$`);
  }

  const regex = convertGlobToRegex(pattern);

  function walk(currentDir) {
    if (results.length >= maxResults) return;
    let entries;
    try {
      entries = fs.readdirSync(currentDir, { withFileTypes: true });
    } catch (e) {
      return;
    }

    for (const entry of entries) {
      if (results.length >= maxResults) break;
      const fullPath = path.join(currentDir, entry.name);
      const relPath = path.relative(root, fullPath).replace(/\\/g, '/');
      const relFromSearch = path.relative(targetDir, fullPath).replace(/\\/g, '/');

      if (regex.test(relPath) || regex.test(relFromSearch) || regex.test(entry.name)) {
        results.push(relPath);
      }

      if (entry.isDirectory() && !ignoreDirs.has(entry.name)) {
        walk(fullPath);
      }
    }
  }

  walk(targetDir);

  return {
    status: 'success',
    pattern,
    count: results.length,
    files: results
  };
}

/**
 * Tool: list
 * List directory contents in workspace.
 */
async function listTool({ path: dirPath = '.', dir }, workspaceRoot) {
  const root = workspaceRoot || process.cwd();
  const target = resolveWorkspacePath(root, dirPath || dir || '.');
  if (!fs.existsSync(target)) {
    throw new Error(`Directory not found: ${dirPath}`);
  }
  const stat = fs.statSync(target);
  if (!stat.isDirectory()) {
    throw new Error(`Path is not a directory: ${dirPath}`);
  }

  const entries = fs.readdirSync(target, { withFileTypes: true });
  const items = entries.map(entry => {
    const full = path.join(target, entry.name);
    let size = 0;
    try {
      if (entry.isFile()) {
        size = fs.statSync(full).size;
      }
    } catch (e) {}
    return {
      name: entry.name,
      type: entry.isDirectory() ? 'directory' : (entry.isFile() ? 'file' : 'other'),
      size
    };
  });

  const relPath = path.relative(root, target).replace(/\\/g, '/') || '.';

  return {
    status: 'success',
    path: relPath,
    itemCount: items.length,
    items
  };
}

/**
 * Tool: bash / exec
 * Execute shell commands bounded to workspace root.
 */
async function bashTool({ command, timeout = 30000 }, workspaceRoot) {
  if (!command) throw new Error("Parameter 'command' is required for bash tool");
  const root = workspaceRoot || process.cwd();
  const cwd = resolveWorkspacePath(root, '.');

  try {
    const stdout = execSync(command, {
      cwd,
      timeout: Math.min(timeout, 60000),
      maxBuffer: 10 * 1024 * 1024,
      encoding: 'utf8',
      env: { ...process.env, PAGER: 'cat' }
    });
    return {
      status: 'success',
      exitCode: 0,
      stdout: stdout.trim(),
      stderr: ''
    };
  } catch (err) {
    return {
      status: 'error',
      exitCode: err.status || 1,
      stdout: (err.stdout || '').trim(),
      stderr: (err.stderr || err.message || '').trim()
    };
  }
}

/**
 * Tool: web_fetch
 * Fetch URL content via HTTP/HTTPS request.
 */
async function webFetchTool({ url, method = 'GET', headers = {}, body }) {
  if (!url) throw new Error("Parameter 'url' is required for web_fetch tool");

  try {
    if (typeof fetch === 'function') {
      const options = {
        method,
        headers: headers || {}
      };
      if (body && ['POST', 'PUT', 'PATCH'].includes(method.toUpperCase())) {
        options.body = typeof body === 'string' ? body : JSON.stringify(body);
      }
      const response = await fetch(url, options);
      const text = await response.text();
      return {
        status: response.status,
        statusText: response.statusText,
        content: text.slice(0, 100000)
      };
    } else {
      const http = url.startsWith('https') ? require('https') : require('http');
      return new Promise((resolve) => {
        const req = http.request(url, { method, headers }, (res) => {
          let data = '';
          res.on('data', (chunk) => { data += chunk; });
          res.on('end', () => {
            resolve({
              status: res.statusCode,
              statusText: res.statusMessage,
              content: data.slice(0, 100000)
            });
          });
        });
        req.on('error', (err) => {
          resolve({ status: 500, statusText: err.message, content: '' });
        });
        if (body) req.write(typeof body === 'string' ? body : JSON.stringify(body));
        req.end();
      });
    }
  } catch (err) {
    return {
      status: 500,
      statusText: err.message,
      content: ''
    };
  }
}

// Full array of workspace tool definitions
const toolDefinitions = [
  {
    name: 'read',
    description: 'Read file contents bounded by workspace root',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Relative path to file' },
        start_line: { type: 'number', description: 'Optional 1-based start line' },
        end_line: { type: 'number', description: 'Optional 1-based end line' }
      },
      required: ['path']
    },
    execute: readTool
  },
  {
    name: 'write',
    description: 'Write file contents inside workspace root',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Relative path to file' },
        content: { type: 'string', description: 'Content to write' }
      },
      required: ['path', 'content']
    },
    execute: writeTool
  },
  {
    name: 'edit',
    description: 'Replace target string with replacement string in a workspace file',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Relative path to file' },
        target: { type: 'string', description: 'Exact string to be replaced' },
        replacement: { type: 'string', description: 'Replacement string' }
      },
      required: ['path', 'target', 'replacement']
    },
    execute: editTool
  },
  {
    name: 'grep',
    description: 'Search workspace files using regex or literal substring',
    parameters: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Search term or regex pattern' },
        path: { type: 'string', description: 'Directory to search within (default ".")' },
        is_regex: { type: 'boolean', description: 'True if query is a regular expression' }
      },
      required: ['query']
    },
    execute: grepTool
  },
  {
    name: 'glob',
    description: 'Find matching file paths in workspace using glob pattern',
    parameters: {
      type: 'object',
      properties: {
        pattern: { type: 'string', description: 'Glob pattern (e.g. "**/*.js")' },
        path: { type: 'string', description: 'Directory to start search (default ".")' }
      },
      required: ['pattern']
    },
    execute: globTool
  },
  {
    name: 'list',
    description: 'List directory contents in workspace',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Directory path (default ".")' }
      }
    },
    execute: listTool
  },
  {
    name: 'bash',
    description: 'Execute shell commands inside workspace root',
    parameters: {
      type: 'object',
      properties: {
        command: { type: 'string', description: 'Shell command to execute' },
        timeout: { type: 'number', description: 'Execution timeout in ms (default 30000)' }
      },
      required: ['command']
    },
    execute: bashTool
  },
  {
    name: 'exec',
    description: 'Alias for bash tool',
    parameters: {
      type: 'object',
      properties: {
        command: { type: 'string', description: 'Shell command to execute' },
        timeout: { type: 'number', description: 'Execution timeout in ms' }
      },
      required: ['command']
    },
    execute: bashTool
  },
  {
    name: 'web_fetch',
    description: 'Fetch content from a URL via HTTP/HTTPS request',
    parameters: {
      type: 'object',
      properties: {
        url: { type: 'string', description: 'URL to fetch' },
        method: { type: 'string', description: 'HTTP method (default GET)' },
        headers: { type: 'object', description: 'HTTP headers object' },
        body: { type: 'string', description: 'Optional request body' }
      },
      required: ['url']
    },
    execute: webFetchTool
  }
];

/**
 * Creates bound workspace tool instances for an OMA runner.
 */
function createWorkspaceTools(workspaceRoot) {
  const root = workspaceRoot || process.cwd();
  return toolDefinitions.map(t => ({
    name: t.name,
    description: t.description,
    parameters: t.parameters,
    execute: (args) => t.name === 'web_fetch' ? t.execute(args) : t.execute(args, root)
  }));
}

/**
 * Executes a tool by name with arguments and workspaceRoot.
 */
async function executeWorkspaceTool(name, args, workspaceRoot) {
  const def = toolDefinitions.find(t => t.name === name);
  if (!def) {
    throw new Error(`Unknown tool: ${name}`);
  }
  if (name === 'web_fetch') {
    return await def.execute(args);
  }
  return await def.execute(args, workspaceRoot || process.cwd());
}

module.exports = {
  toolDefinitions,
  createWorkspaceTools,
  executeWorkspaceTool,
  resolveWorkspacePath,
  readTool,
  writeTool,
  editTool,
  grepTool,
  globTool,
  listTool,
  bashTool,
  webFetchTool
};
