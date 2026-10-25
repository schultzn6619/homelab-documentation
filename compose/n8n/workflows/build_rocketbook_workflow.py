# Builds the Rocketbook -> Obsidian n8n workflow JSON (and a manual-trigger test copy).
import json, sys, uuid

OUT = sys.argv[1]
ROOT = '/home/node/.n8n-files/rocketbook'

PREPARE = r"""
// One item per scan attachment, named after the email's date and subject.
const sanitize = s => (s || '').replace(/[\\/]/g, '-').replace(/:/g, ' -')
  .replace(/[*?"<>|#^\[\]{}]/g, '').replace(/\s+/g, ' ').trim();
const extFor = (b) => {
  const fromName = ((b.fileName || '').match(/\.([A-Za-z0-9]+)$/) || [])[1];
  if (fromName) return fromName.toLowerCase();
  return { 'application/pdf': 'pdf', 'image/jpeg': 'jpg', 'image/png': 'png' }[b.mimeType] || 'bin';
};
const usedBases = new Set();
const out = [];
$input.all().forEach((item, email) => {
  const received = DateTime.fromJSDate(new Date(item.json.date || Date.now())).setZone('America/New_York');
  // Rocketbook's default subject is "RB <scan time>.pdf-<send time>"; use the scan time and a plain title.
  const rb = (item.json.subject || '').match(/^RB (\d{4}-\d{2}-\d{2}) (\d{2})\.(\d{2})\.(\d{2})/);
  const scanned = rb ? DateTime.fromISO(`${rb[1]}T${rb[2]}:${rb[3]}:${rb[4]}`, { zone: 'America/New_York' }) : received;
  // Smart Title subjects can carry the same ".pdf-<send time>" suffix; drop it from the title.
  const subjectTitle = (item.json.subject || '').replace(/\.(pdf|jpe?g|png)-[\d\/.: -]*$/i, '');
  const title = rb ? 'Rocketbook scan' : (sanitize(subjectTitle).slice(0, 80) || 'Rocketbook scan');
  const stamp = scanned.toFormat('yyyy-MM-dd HHmmss');
  let base = `${stamp} ${title}`;
  for (let n = 2; usedBases.has(base); n++) base = `${stamp} ${title} ${n}`;
  usedBases.add(base);
  const keys = Object.keys(item.binary || {}).sort();
  keys.forEach((key, i) => {
    const bin = item.binary[key];
    const ext = extFor(bin);
    const fileName = `${base}${keys.length > 1 ? ' ' + (i + 1) : ''}.${ext}`;
    out.push({
      json: {
        email, base, fileName, isPdf: ext === 'pdf',
        subject: item.json.subject || '',
        scanned: scanned.toISO({ suppressMilliseconds: true }),
        received: received.toISO({ suppressMilliseconds: true }),
        body: (item.json.text || '').trim(),
      },
      binary: { data: { ...bin, fileName } },
      pairedItem: { item: email },
    });
  });
});
return out;
""".strip()

BUILD = r"""
// Group the files back by email and write one Markdown note per scan.
const prepared = $('Prepare files').all();
const extracted = $input.all();
const emails = new Map();
prepared.forEach((p, idx) => {
  const j = p.json;
  if (!emails.has(j.email)) emails.set(j.email, { ...j, files: [], text: [] });
  const e = emails.get(j.email);
  e.files.push(j.fileName);
  const t = extracted[idx] && extracted[idx].json && extracted[idx].json.text;
  if (j.isPdf && typeof t === 'string' && t.trim()) e.text.push(t.trim());
});
const callout = (title, text) => `> [!note]- ${title}\n` + text.split('\n').map(l => '> ' + l).join('\n');
// Class codes written in a Smart Title, e.g. "##DE L3a##". The filer on the host moves the note
// to "<class>/Lecture <n>/" based on the class and lecture properties set here.
const CLASSES = { DE: 'Digital Electronics', LF: 'Linux Fundamentals', NA: 'Network Admin 1', STS: 'Science, Tech, and Society' };
const CODE = new RegExp(`\\b(${Object.keys(CLASSES).join('|')})\\s*-?\\s*L(?:EC(?:TURE)?)?\\s*-?\\s*(\\d{1,2})\\s*([AB])?\\b`, 'i');
const findCode = e => {
  // The subject is a Smart Title when one was written; fall back to a ##...## code in the scanned text.
  const tagged = [e.body, ...e.text].map(t => (t.match(/##([^#]{1,60})##/) || [])[1]).filter(Boolean);
  for (const s of [e.subject, ...tagged]) {
    const m = (s || '').match(CODE);
    if (m) return { cls: CLASSES[m[1].toUpperCase()], lecture: `${Number(m[2])}${(m[3] || '').toLowerCase()}` };
  }
  return null;
};
return [...emails.values()].map(e => {
  const code = findCode(e);
  const parts = [
    '---',
    `created: ${e.scanned}`,
    `received: ${e.received}`,
    'source: rocketbook',
    `email_subject: ${JSON.stringify(e.subject)}`,
    ...(code ? [`class: ${JSON.stringify(code.cls)}`, `lecture: ${JSON.stringify(code.lecture)}`] : []),
    'tags:',
    '  - rocketbook',
    '---',
    '',
    e.files.map(f => `![[${f}]]`).join('\n\n'),
  ];
  if (e.body) parts.push('', callout('Email text', e.body));
  if (e.text.length) parts.push('', callout('Text from the scan', e.text.join('\n\n')));
  const md = parts.join('\n') + '\n';
  return {
    json: { noteFile: `${e.base}.md` },
    binary: { data: { data: Buffer.from(md, 'utf8').toString('base64'), mimeType: 'text/markdown', fileName: `${e.base}.md`, fileExtension: 'md' } },
  };
});
""".strip()

def node(name, type_, version, params, pos, **extra):
    return {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'rocketbook/' + name)), 'name': name, 'type': type_,
            'typeVersion': version, 'position': pos, 'parameters': params, **extra}

common = [
    node('Prepare files', 'n8n-nodes-base.code', 2, {'jsCode': PREPARE}, [220, 300]),
    node('Save scan', 'n8n-nodes-base.readWriteFile', 1, {
        'operation': 'write', 'fileName': f'={ROOT}/scans/{{{{ $json.fileName }}}}', 'dataPropertyName': 'data', 'options': {}},
        [440, 200]),
    node('Extract PDF text', 'n8n-nodes-base.extractFromFile', 1.1, {
        'operation': 'pdf', 'binaryPropertyName': 'data', 'options': {}}, [440, 400], onError='continueRegularOutput'),
    node('Build note', 'n8n-nodes-base.code', 2, {'jsCode': BUILD}, [660, 400]),
    node('Save note', 'n8n-nodes-base.readWriteFile', 1, {
        'operation': 'write', 'fileName': f'={ROOT}/{{{{ $json.noteFile }}}}', 'dataPropertyName': 'data', 'options': {}},
        [880, 400]),
]
conns = {
    'Prepare files': {'main': [[{'node': 'Save scan', 'type': 'main', 'index': 0},
                                {'node': 'Extract PDF text', 'type': 'main', 'index': 0}]]},
    'Extract PDF text': {'main': [[{'node': 'Build note', 'type': 'main', 'index': 0}]]},
    'Build note': {'main': [[{'node': 'Save note', 'type': 'main', 'index': 0}]]},
}
settings = {'executionOrder': 'v1', 'timezone': 'America/New_York'}

trigger = node('Rocketbook email', 'n8n-nodes-base.emailReadImap', 2.2,
               {'mailbox': 'Rocketbook', 'postProcessAction': 'read', 'format': 'resolved', 'options': {}}, [0, 300],
               credentials={'imap': {'id': 'ErOWBxN7IR8dCcM5', 'name': 'IMAP account'}})
real = {'id': '222vE75UnIzLLH0z', 'name': 'Rocketbook → Obsidian', 'active': False, 'settings': settings,
        'nodes': [trigger] + common, 'connections': {'Rocketbook email': {'main': [[{'node': 'Prepare files', 'type': 'main', 'index': 0}]]}, **conns}}

# Test copy: a manual trigger and a fake email carrying a small PDF, then the same nodes.
FAKE = r"""
const pdf = `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 52>>stream
BT /F1 18 Tf 20 50 Td (Handwritten test page) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>
%%EOF`;
const scan = () => ({ attachment_0: { data: Buffer.from(pdf).toString('base64'), mimeType: 'application/pdf', fileName: 'scan.pdf', fileExtension: 'pdf' } });
// Three cases: Smart Title code, default subject (stays in the inbox), code only in the scanned text.
return [
  { json: { subject: 'DE L9b pipeline test.pdf-10/25/2026-16.40.00', date: new Date().toISOString(), text: '' }, binary: scan() },
  { json: { subject: 'RB 2026-08-28 09.00.00.pdf-10/25/2026-16.40.30', date: new Date().toISOString(), text: 'Sent from Rocketbook.\nTranscription line one.' }, binary: scan() },
  { json: { subject: 'RB 2026-08-27 10.00.00.pdf-10/25/2026-16.41.00', date: new Date().toISOString(), text: 'Sent from Rocketbook.\n##sts lecture 9## topic' }, binary: scan() },
];
""".strip()
test = {'id': 'rbTestPipeline01', 'name': 'Rocketbook → Obsidian (test)', 'active': False, 'settings': settings,
        'nodes': [node('Manual', 'n8n-nodes-base.manualTrigger', 1, {}, [-220, 300]),
                  node('Fake email', 'n8n-nodes-base.code', 2, {'jsCode': FAKE}, [0, 300])] + common,
        'connections': {'Manual': {'main': [[{'node': 'Fake email', 'type': 'main', 'index': 0}]]},
                        'Fake email': {'main': [[{'node': 'Prepare files', 'type': 'main', 'index': 0}]]}, **conns}}

json.dump(real, open(f'{OUT}/rocketbook-obsidian.json', 'w'), indent=2, ensure_ascii=False)
json.dump(test, open(f'{OUT}/rocketbook-obsidian-test.json', 'w'), indent=2, ensure_ascii=False)
print('ok')
