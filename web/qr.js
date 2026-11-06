// A small QR code encoder (byte mode, error correction level M, versions 1–10) for the phone pairing link,
// so a phone can pair by pointing its camera at the computer screen. Follows ISO/IEC 18004; no dependencies.

// Level M per version: total codewords, error-correction codewords per block, number of blocks.
const VERSIONS = [null, [26, 10, 1], [44, 16, 1], [70, 26, 1], [100, 18, 2], [134, 24, 2], [172, 16, 4], [196, 18, 4], [242, 22, 4], [292, 22, 5], [346, 26, 5]];
const ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];
const bit = (x, i) => ((x >>> i) & 1) !== 0;

function gfMultiply(x, y) {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
}

export function reedSolomon(data, degree) {
  const divisor = new Array(degree).fill(0);
  divisor[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < divisor.length; j++) {
      divisor[j] = gfMultiply(divisor[j], root);
      if (j + 1 < divisor.length) divisor[j] ^= divisor[j + 1];
    }
    root = gfMultiply(root, 0x02);
  }
  const result = new Array(degree).fill(0);
  for (const b of data) {
    const factor = b ^ result.shift();
    result.push(0);
    divisor.forEach((coef, i) => { result[i] ^= gfMultiply(coef, factor); });
  }
  return result;
}

function encodeData(bytes, version) {
  const [total, ecc, blocks] = VERSIONS[version];
  const capacity = total - ecc * blocks;
  const bits = [];
  const put = (value, length) => { for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
  put(0b0100, 4);
  put(bytes.length, version < 10 ? 8 : 16);
  for (const b of bytes) put(b, 8);
  put(0, Math.min(4, capacity * 8 - bits.length));
  put(0, (8 - (bits.length % 8)) % 8);
  const data = [];
  for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  for (let pad = 0xec; data.length < capacity; pad ^= 0xec ^ 0x11) data.push(pad);
  // Split into blocks, add error correction, interleave.
  const shortBlocks = blocks - (total % blocks), shortLength = Math.floor(total / blocks);
  const parts = [];
  for (let i = 0, k = 0; i < blocks; i++) {
    const length = shortLength - ecc + (i < shortBlocks ? 0 : 1);
    const block = data.slice(k, k + length);
    k += length;
    const correction = reedSolomon(block, ecc);
    if (i < shortBlocks) block.push(0);
    parts.push(block.concat(correction));
  }
  const out = [];
  for (let i = 0; i < parts[0].length; i++) {
    parts.forEach((block, j) => { if (i !== shortLength - ecc || j >= shortBlocks) out.push(block[i]); });
  }
  return out;
}

class QrSymbol {
  constructor(version) {
    this.size = version * 4 + 17;
    this.modules = Array.from({ length: this.size }, () => new Array(this.size).fill(false));
    this.fixed = Array.from({ length: this.size }, () => new Array(this.size).fill(false));
    this.version = version;
  }
  set(x, y, dark) { this.modules[y][x] = dark; this.fixed[y][x] = true; }
  functionPatterns() {
    const n = this.size;
    for (let i = 0; i < n; i++) { this.set(6, i, i % 2 === 0); this.set(i, 6, i % 2 === 0); }
    for (const [cx, cy] of [[3, 3], [n - 4, 3], [3, n - 4]]) {
      for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx, y = cy + dy, d = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < n && y >= 0 && y < n) this.set(x, y, d !== 2 && d !== 4);
      }
    }
    const align = ALIGN[this.version], last = align.length - 1;
    align.forEach((ay, i) => align.forEach((ax, j) => {
      if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) this.set(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }));
    this.format(0);
    if (this.version >= 7) {
      let rem = this.version;
      for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
      const bits = (this.version << 12) | rem;
      for (let i = 0; i < 18; i++) {
        const a = n - 11 + (i % 3), b = Math.floor(i / 3);
        this.set(a, b, bit(bits, i));
        this.set(b, a, bit(bits, i));
      }
    }
  }
  format(mask) {
    const data = (0b00 << 3) | mask; // level M
    let rem = data;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const bits = ((data << 10) | rem) ^ 0x5412, n = this.size;
    for (let i = 0; i <= 5; i++) this.set(8, i, bit(bits, i));
    this.set(8, 7, bit(bits, 6));
    this.set(8, 8, bit(bits, 7));
    this.set(7, 8, bit(bits, 8));
    for (let i = 9; i < 15; i++) this.set(14 - i, 8, bit(bits, i));
    for (let i = 0; i < 8; i++) this.set(n - 1 - i, 8, bit(bits, i));
    for (let i = 8; i < 15; i++) this.set(8, n - 15 + i, bit(bits, i));
    this.set(8, n - 8, true);
  }
  place(codewords) {
    const n = this.size;
    let i = 0;
    for (let right = n - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < n; vert++) for (let j = 0; j < 2; j++) {
        const x = right - j, y = ((right + 1) & 2) === 0 ? n - 1 - vert : vert;
        if (!this.fixed[y][x] && i < codewords.length * 8) { this.modules[y][x] = bit(codewords[i >>> 3], 7 - (i & 7)); i++; }
      }
    }
  }
  mask(m) {
    const rules = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
      (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
      (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0];
    for (let y = 0; y < this.size; y++) for (let x = 0; x < this.size; x++) if (!this.fixed[y][x] && rules[m](x, y)) this.modules[y][x] = !this.modules[y][x];
  }
  penalty() {
    const n = this.size, m = this.modules;
    let score = 0, dark = 0;
    const lines = [];
    for (let i = 0; i < n; i++) { lines.push(m[i]); lines.push(m.map((row) => row[i])); }
    for (const line of lines) {
      let run = 1;
      for (let i = 1; i <= n; i++) {
        if (i < n && line[i] === line[i - 1]) run++;
        else { if (run >= 5) score += run - 2; run = 1; }
      }
      const text = line.map((v) => (v ? "1" : "0")).join("");
      for (const pattern of ["10111010000", "00001011101"]) for (let at = text.indexOf(pattern); at >= 0; at = text.indexOf(pattern, at + 1)) score += 40;
    }
    for (let y = 0; y + 1 < n; y++) for (let x = 0; x + 1 < n; x++) {
      const v = m[y][x];
      if (v === m[y][x + 1] && v === m[y + 1][x] && v === m[y + 1][x + 1]) score += 3;
    }
    for (const row of m) for (const v of row) if (v) dark++;
    return score + Math.floor(Math.abs((dark * 100) / (n * n) - 50) / 5) * 10;
  }
}

/** The QR matrix (rows of booleans, true = dark) for a short text such as a URL. */
export function qrMatrix(text) {
  const bytes = [...new TextEncoder().encode(text)];
  let version = 1;
  while (version <= 10) {
    const [total, ecc, blocks] = VERSIONS[version];
    if (4 + (version < 10 ? 8 : 16) + bytes.length * 8 <= (total - ecc * blocks) * 8) break;
    version++;
  }
  if (version > 10) throw new Error("Text too long for a QR code here");
  const codewords = encodeData(bytes, version);
  let best = null, bestScore = Infinity;
  for (let m = 0; m < 8; m++) {
    const symbol = new QrSymbol(version);
    symbol.functionPatterns();
    symbol.place(codewords);
    symbol.mask(m);
    symbol.format(m);
    const score = symbol.penalty();
    if (score < bestScore) { best = symbol; bestScore = score; }
  }
  return best.modules;
}

/** An SVG drawing of the QR code with the required quiet zone, dark modules on white. Colours are inline styles so a
 * page stylesheet for icons (fill:none; stroke:…) cannot hollow the modules out. */
export function qrSvg(text, scale = 5) {
  const matrix = qrMatrix(text), n = matrix.length, quiet = 4, size = (n + quiet * 2) * scale;
  let path = "";
  matrix.forEach((row, y) => row.forEach((dark, x) => { if (dark) path += `M${(x + quiet) * scale} ${(y + quiet) * scale}h${scale}v${scale}h-${scale}z`; }));
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" style="fill:none;stroke:none"><rect width="100%" height="100%" style="fill:#fff;stroke:none"/><path d="${path}" style="fill:#000;stroke:none"/></svg>`;
}
