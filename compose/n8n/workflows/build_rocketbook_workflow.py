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
  const title = sanitize(item.json.subject).slice(0, 80) || 'Rocketbook scan';
  let base = `${received.toFormat('yyyy-MM-dd HHmmss')} ${title}`;
  for (let n = 2; usedBases.has(base); n++) base = `${received.toFormat('yyyy-MM-dd HHmmss')} ${title} ${n}`;
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
return [...emails.values()].map(e => {
  const parts = [
    '---',
    `created: ${e.received}`,
    'source: rocketbook',
    `email_subject: ${JSON.stringify(e.subject)}`,
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
return [{ json: { subject: 'n8n pipeline test: Weekly plan', date: new Date().toISOString(), text: 'Sent from Rocketbook.\nTranscription line one.' },
  binary: { attachment_0: { data: Buffer.from(pdf).toString('base64'), mimeType: 'application/pdf', fileName: 'scan.pdf', fileExtension: 'pdf' } } }];
""".strip()
test = {'id': 'rbTestPipeline01', 'name': 'Rocketbook → Obsidian (test)', 'active': False, 'settings': settings,
        'nodes': [node('Manual', 'n8n-nodes-base.manualTrigger', 1, {}, [-220, 300]),
                  node('Fake email', 'n8n-nodes-base.code', 2, {'jsCode': FAKE}, [0, 300])] + common,
        'connections': {'Manual': {'main': [[{'node': 'Fake email', 'type': 'main', 'index': 0}]]},
                        'Fake email': {'main': [[{'node': 'Prepare files', 'type': 'main', 'index': 0}]]}, **conns}}

json.dump(real, open(f'{OUT}/rocketbook-obsidian.json', 'w'), indent=2, ensure_ascii=False)
json.dump(test, open(f'{OUT}/rocketbook-obsidian-test.json', 'w'), indent=2, ensure_ascii=False)
print('ok')
