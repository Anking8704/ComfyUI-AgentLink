// The pairing QR code must scan: checked against the textbook Reed–Solomon example, then by decoding generated
// symbols with OpenCV (from ComfyUI's Python, when available) for every version the pairing link can need.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { spawnSync } = require('node:child_process');

function bmp(matrix, scale = 6, quiet = 4) {
  const n = matrix.length, size = (n + quiet * 2) * scale, row = Math.ceil(size / 4) * 4;
  const header = Buffer.alloc(54 + 1024), pixels = Buffer.alloc(row * size, 255);
  header.write('BM'); header.writeUInt32LE(54 + 1024 + pixels.length, 2); header.writeUInt32LE(54 + 1024, 10);
  header.writeUInt32LE(40, 14); header.writeInt32LE(size, 18); header.writeInt32LE(size, 22); header.writeUInt16LE(1, 26); header.writeUInt16LE(8, 28);
  header.writeUInt32LE(pixels.length, 34); header.writeUInt32LE(256, 46);
  for (let i = 0; i < 256; i++) header.writeUInt32LE(i * 0x010101, 54 + i * 4);
  matrix.forEach((cells, y) => cells.forEach((dark, x) => {
    if (!dark) return;
    for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
      const py = size - 1 - ((y + quiet) * scale + dy), px = (x + quiet) * scale + dx;
      pixels[py * row + px] = 0;
    }
  }));
  return Buffer.concat([header, pixels]);
}

(async () => {
  const { qrMatrix, reedSolomon, qrSvg } = await import(pathToFileURL(path.resolve('web/qr.js')).href);
  // "HELLO WORLD", version 1-M: the data codewords and their known error-correction codewords.
  assert.deepEqual(reedSolomon([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17], 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]);
  const texts = ['123456', 'http://10.200.42.113:8188/agentlink/pair?code=042917&next=%2F%3Fagentlink%3Dopen',
    'http://192.168.100.200:8188/agentlink/pair?code=000001&next=%2F%3Fagentlink%3Dopen&extra=' + 'x'.repeat(70),
    '中文配对 ' + 'y'.repeat(150)];
  const sizes = texts.map((t) => qrMatrix(t).length);
  assert.ok(sizes[3] >= 45, 'long texts use versions with version information');
  assert.match(qrSvg(texts[1]), /^<svg [^>]+><rect[^>]+\/><path d="M/);
  const python = ['R:/ComfyUI-aki-v3.2/python/python.exe', path.resolve('../python/python.exe'), 'python'].find((p) => p === 'python' || fs.existsSync(p));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'agentlink-qr-'));
  const files = texts.map((t, i) => { const f = path.join(dir, `qr${i}.bmp`); fs.writeFileSync(f, bmp(qrMatrix(t))); return f; });
  const script = 'import sys,cv2,json\nd=cv2.QRCodeDetector()\nprint(json.dumps([d.detectAndDecode(cv2.imread(f))[0] for f in sys.argv[1:]]))';
  const run = spawnSync(python, ['-I', '-c', script, ...files], { encoding: 'utf8' });
  if (run.status !== 0) { console.log(`QR codewords checked; OpenCV decode skipped (${(run.stderr || '').split('\n').filter(Boolean).pop() || 'no python'})`); return; }
  const decoded = JSON.parse(run.stdout.trim().split('\n').pop());
  assert.deepEqual(decoded, texts, 'OpenCV reads back every generated code');
  fs.rmSync(dir, { recursive: true, force: true });
  console.log(`QR: Reed–Solomon vector and OpenCV decode of versions ${sizes.map((s) => (s - 17) / 4).join(', ')} passed`);
})().catch((e) => { console.error(e); process.exitCode = 1; });
