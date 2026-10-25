// Convert a Trilium document.db into an Obsidian vault.
// Usage: node convert.js <document.db> <out-vault-dir>
const fs = require('fs');
const path = require('path');
const Database = require('better-sqlite3');
const TurndownService = require('turndown');
const { gfm } = require('turndown-plugin-gfm');

const [dbPath, outDir] = process.argv.slice(2);
const db = new Database(dbPath, { readonly: true });
const ATTACH_DIR = '_attachments';

const notes = new Map();
for (const n of db.prepare(`select n.*, b.content from notes n left join blobs b using(blobId) where n.isDeleted=0`).all()) notes.set(n.noteId, n);
const children = new Map();
for (const b of db.prepare(`select * from branches where isDeleted=0 order by notePosition`).all()) {
  if (!children.has(b.parentNoteId)) children.set(b.parentNoteId, []);
  children.get(b.parentNoteId).push(b);
}
const attrs = new Map();
for (const a of db.prepare(`select * from attributes where isDeleted=0 and type='label'`).all()) {
  if (!attrs.has(a.noteId)) attrs.set(a.noteId, {});
  attrs.get(a.noteId)[a.name] = a.value;
}
const attachments = new Map();
for (const a of db.prepare(`select a.*, b.content from attachments a join blobs b using(blobId) where a.isDeleted=0`).all()) attachments.set(a.attachmentId, a);

const sanitize = s => s.replace(/[\\/]/g, '-').replace(/:/g, ' -').replace(/[*?"<>|#^\[\]]/g, '').replace(/\s+/g, ' ').trim() || 'Untitled';
const usedPaths = new Set();
function unique(p) {
  const ext = path.extname(p), base = p.slice(0, p.length - ext.length);
  let cand = p, i = 2;
  while (usedPaths.has(cand.toLowerCase())) cand = `${base} ${i++}${ext}`;
  usedPaths.add(cand.toLowerCase());
  return cand;
}
const toDate = s => new Date(s.replace(' ', 'T').replace(/Z?$/, 'Z'));
const report = { written: [], skippedEmpty: [] /* written as empty notes */, attachments: [], other: [] };

function writeFile(rel, data, note) {
  const abs = path.join(outDir, rel);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, data);
  if (note) { const m = toDate(note.utcDateModified); fs.utimesSync(abs, m, m); }
}

function makeTurndown(note, imageMap) {
  const td = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-', hr: '---', emDelimiter: '*' });
  td.use(gfm);
  td.addRule('fencedCode', {
    filter: n => n.nodeName === 'PRE' && n.firstChild && n.firstChild.nodeName === 'CODE',
    replacement: (_c, n) => {
      const code = n.firstChild;
      let lang = ((code.getAttribute('class') || '').match(/language-(\S+)/) || [])[1] || '';
      if (lang.startsWith('text-x-trilium') || lang === 'text-plain') lang = '';
      lang = lang.replace(/^(text|application)-(x-)?/, '');
      const body = code.textContent.replace(/\n$/, '');
      const fence = body.includes('```') ? '~~~~' : '```';
      return `\n\n${fence}${lang}\n${body}\n${fence}\n\n`;
    },
  });
  td.addRule('triliumImage', {
    filter: 'img',
    replacement: (_c, n) => {
      const m = (n.getAttribute('src') || '').match(/attachments\/([A-Za-z0-9_]+)\//);
      if (m && imageMap[m[1]]) return `![[${imageMap[m[1]]}]]`;
      report.other.push(`${note.title}: unresolved image ${n.getAttribute('src')}`);
      return `![](${n.getAttribute('src')})`;
    },
  });
  td.addRule('listItem', {
    filter: 'li',
    replacement: (content, n, options) => {
      content = content.replace(/^\n+/, '').replace(/\n+$/, '\n').replace(/\n/gm, '\n    ');
      const parent = n.parentNode;
      let prefix = '- ';
      if (parent.nodeName === 'OL') {
        const start = parent.getAttribute('start');
        prefix = (start ? Number(start) : 1) + Array.prototype.indexOf.call(parent.children, n) + '. ';
      }
      return prefix + content + (n.nextSibling && !/\n$/.test(content) ? '\n' : '');
    },
  });
  td.addRule('figure', { filter: 'figure', replacement: c => `\n\n${c.trim()}\n\n` });
  return td;
}

function noteMarkdown(note, name) {
  // Save image attachments first so the HTML can point at them.
  const imageMap = {};
  let i = 1;
  for (const a of attachments.values()) {
    if (a.ownerId !== note.noteId || a.role !== 'image') continue;
    const ext = path.extname(a.title) || '.png';
    const rel = unique(`${ATTACH_DIR}/${name} ${i++}${ext}`);
    writeFile(rel, a.content, note);
    imageMap[a.attachmentId] = path.basename(rel);
    report.attachments.push(rel);
  }
  let html = note.content == null ? '' : note.content.toString();
  let md = makeTurndown(note, imageMap).turndown(html).replace(/\n{3,}/g, '\n\n').trim();
  // Turndown escapes "1." at the start of headings; the escape is not needed there.
  md = md.replace(/^(#+ \d+)\\\./gm, '$1.');
  return md;
}

function frontmatter(note, extra = {}) {
  const fm = { created: note.utcDateCreated.slice(0, 19).replace(' ', 'T') + 'Z', modified: note.utcDateModified.slice(0, 19).replace(' ', 'T') + 'Z', trilium_id: note.noteId, ...extra };
  return '---\n' + Object.entries(fm).map(([k, v]) => `${k}: ${v}`).join('\n') + '\n---\n\n';
}

function walk(parentId, dir) {
  for (const b of children.get(parentId) || []) {
    const note = notes.get(b.noteId);
    if (!note || note.noteId.startsWith('_')) continue;
    const a = attrs.get(note.noteId) || {};
    let name = sanitize((b.prefix ? b.prefix + ' - ' : '') + note.title);
    // Journal: day notes become YYYY-MM-DD, month notes YYYY-MM, matching Obsidian's daily-notes naming.
    if (a.dateNote) name = a.dateNote;
    else if (a.monthNote) name = a.monthNote;
    const hasKids = (children.get(note.noteId) || []).some(c => !c.noteId.startsWith('_'));
    const childDir = path.join(dir, name);

    if (note.type === 'text' || (note.type === 'code')) {
      let body = note.type === 'text' ? noteMarkdown(note, name) : (note.mime === 'text/x-markdown' ? note.content.toString() : '```\n' + note.content.toString() + '\n```');
      if (body.trim() || !hasKids) {
        const rel = unique(path.join(dir, name + '.md'));
        writeFile(rel, frontmatter(note) + body + '\n', note);
        report.written.push(rel);
        if (!body.trim()) report.skippedEmpty.push(rel);
      }
    } else if (note.type === 'file') {
      const ext = { 'application/pdf': '.pdf' }[note.mime] || '';
      const fname = sanitize(a.originalFileName || note.title);
      const rel = unique(path.join(dir, fname.endsWith(ext) ? fname : fname + ext));
      writeFile(rel, note.content, note);
      report.written.push(rel);
    } else if (note.type !== 'book') {
      report.other.push(`${path.join(dir, name)}: note type '${note.type}' not converted`);
    }
    if (hasKids) walk(note.noteId, childDir);
  }
}

fs.mkdirSync(outDir, { recursive: true });
walk('root', '');

// Obsidian settings: attachment folder and daily notes matching the Journal layout.
writeFile('.obsidian/app.json', JSON.stringify({ attachmentFolderPath: ATTACH_DIR, newLinkFormat: 'shortest', useMarkdownLinks: false }, null, 2));
writeFile('.obsidian/daily-notes.json', JSON.stringify({ folder: 'Journal', format: 'YYYY/YYYY-MM/YYYY-MM-DD' }, null, 2));
writeFile('.obsidian/core-plugins.json', JSON.stringify({ 'file-explorer': true, 'global-search': true, switcher: true, graph: true, backlink: true, 'page-preview': true, 'daily-notes': true, templates: true, 'note-composer': true, 'command-palette': true, 'editor-status': true, bookmarks: true, outline: true, 'word-count': true, 'file-recovery': true, sync: false }, null, 2));

console.log(JSON.stringify(report, null, 2));
