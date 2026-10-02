import { describe, it, expect } from "vitest";
import {
  buildOgg,
  oggCrc,
  parseWebmOpus,
  pickRecorderFormat,
  remuxWebmOpusToOgg,
  type AudioPacket,
} from "./voiceFormat";

// ---------------------------------------------------------------------------
// Мини-писатель EBML — чтобы собрать валидный WebM-фикстур без внешних файлов.
// ---------------------------------------------------------------------------

function bytes(...xs: number[]): Uint8Array {
  return new Uint8Array(xs);
}

function cat(...parts: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

function ebmlSize(n: number): Uint8Array {
  if (n < 0x7f) return bytes(0x80 | n);
  if (n < 0x3fff) return bytes(0x40 | (n >> 8), n & 0xff);
  if (n < 0x1fffff) return bytes(0x20 | (n >> 16), (n >> 8) & 0xff, n & 0xff);
  return bytes(0x10 | (n >> 24), (n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff);
}

function elem(id: number[], content: Uint8Array): Uint8Array {
  return cat(new Uint8Array(id), ebmlSize(content.length), content);
}

function uintElem(id: number[], value: number): Uint8Array {
  const b: number[] = [];
  let v = value;
  do {
    b.unshift(v & 0xff);
    v = Math.floor(v / 256);
  } while (v > 0);
  return elem(id, new Uint8Array(b));
}

function strElem(id: number[], s: string): Uint8Array {
  return elem(id, new Uint8Array([...s].map((c) => c.charCodeAt(0))));
}

function float64Elem(id: number[], value: number): Uint8Array {
  const b = new Uint8Array(8);
  new DataView(b.buffer).setFloat64(0, value, false);
  return elem(id, b);
}

const FRAME = bytes(0x83, 1, 2, 3, 4); // TOC 0x83 → 960 сэмплов

const OPUS_HEAD = (() => {
  const b = new Uint8Array(19);
  for (let i = 0; i < "OpusHead".length; i++) b[i] = "OpusHead".charCodeAt(i);
  b[8] = 1; // version
  b[9] = 1; // channels
  b[12] = 0x80; // 48000 LE
  b[13] = 0xbb;
  return b;
})();

function simpleBlock(track: number, rel: number, flags: number, frame: Uint8Array): Uint8Array {
  const b = new Uint8Array(4 + frame.length);
  b[0] = 0x80 | track; // vint длиной 1 байт
  b[1] = (rel >> 8) & 0xff;
  b[2] = rel & 0xff;
  b[3] = flags;
  b.set(frame, 4);
  return b;
}

function buildWebm(): Uint8Array {
  const tracks = elem(
    [0x16, 0x54, 0xae, 0x6b],
    elem(
      [0xae],
      cat(
        uintElem([0xd7], 1),
        uintElem([0x83], 2),
        strElem([0x86], "A_OPUS"),
        elem([0x63, 0xa2], OPUS_HEAD),
        elem([0xe1], cat(float64Elem([0xb5], 48000), uintElem([0x9f], 1))),
      ),
    ),
  );
  const cluster = elem(
    [0x1f, 0x43, 0xb6, 0x75],
    cat(uintElem([0xe7], 0), elem([0xa3], simpleBlock(1, 0, 0x80, FRAME))),
  );
  const segment = elem([0x18, 0x53, 0x80, 0x67], cat(tracks, cluster));
  const header = elem([0x1a, 0x45, 0xdf, 0xa3], strElem([0x42, 0x86], "webm"));
  return cat(header, segment);
}

// ---------------------------------------------------------------------------
// Мини-читатель Ogg — для проверки результата.
// ---------------------------------------------------------------------------

interface Page {
  offset: number;
  length: number;
  headerType: number;
  granule: number;
  segCount: number;
}

function readPages(ogg: Uint8Array): Page[] {
  const pages: Page[] = [];
  let p = 0;
  while (p < ogg.length) {
    if (!(ogg[p] === 0x4f && ogg[p + 1] === 0x67 && ogg[p + 2] === 0x67 && ogg[p + 3] === 0x53)) {
      throw new Error(`no OggS at ${p}`);
    }
    const segCount = ogg[p + 26];
    let body = 0;
    for (let i = 0; i < segCount; i++) body += ogg[p + 27 + i];
    const len = 27 + segCount + body;
    const dv = new DataView(ogg.buffer, ogg.byteOffset + p + 6, 8);
    const lo = dv.getUint32(0, true);
    const hi = dv.getUint32(4, true);
    pages.push({
      offset: p,
      length: len,
      headerType: ogg[p + 5],
      granule: lo + hi * 0x100000000,
      segCount,
    });
    p += len;
  }
  return pages;
}

function allPackets(ogg: Uint8Array): Uint8Array[] {
  const packets: Uint8Array[] = [];
  let cur: number[] = [];
  for (const pg of readPages(ogg)) {
    let o = pg.offset + 27 + pg.segCount;
    for (let i = 0; i < pg.segCount; i++) {
      const lace = ogg[pg.offset + 27 + i];
      for (let j = 0; j < lace; j++) cur.push(ogg[o++]);
      if (lace < 255) {
        packets.push(new Uint8Array(cur));
        cur = [];
      }
    }
  }
  if (cur.length) packets.push(new Uint8Array(cur));
  return packets;
}

// ---------------------------------------------------------------------------

describe("parseWebmOpus", () => {
  it("достаёт OpusHead и аудио-пакеты с гранулами", () => {
    const parsed = parseWebmOpus(buildWebm().buffer as ArrayBuffer);
    expect(new TextDecoder().decode(parsed.head.slice(0, 8))).toBe("OpusHead");
    expect(parsed.packets.length).toBe(1);
    expect(Array.from(parsed.packets[0].data)).toEqual([...FRAME]);
    expect(parsed.packets[0].granule).toBe(960);
  });

  it("отбивает не-WebM данные", () => {
    expect(() => parseWebmOpus(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]).buffer)).toThrow();
  });
});

describe("buildOgg", () => {
  it("делает валидные страницы с самосогласованным CRC", () => {
    const { head, packets } = parseWebmOpus(buildWebm().buffer as ArrayBuffer);
    const ogg = buildOgg(head, packets);
    const pages = readPages(ogg);
    expect(pages.length).toBe(3);
    expect(pages[0].headerType & 0x02).toBe(0x02); // BOS
    expect(pages[2].headerType & 0x04).toBe(0x04); // EOS
    for (const pg of pages) {
      const stored = new DataView(ogg.buffer, ogg.byteOffset + pg.offset + 22, 4).getUint32(0, true);
      const copy = ogg.slice(pg.offset, pg.offset + pg.length);
      new DataView(copy.buffer).setUint32(22, 0, true);
      expect(oggCrc(copy)).toBe(stored);
    }
  });

  it("сохраняет аудио-пакет без изменений", () => {
    const { head, packets } = parseWebmOpus(buildWebm().buffer as ArrayBuffer);
    const ogg = buildOgg(head, packets);
    const decoded = allPackets(ogg);
    expect(new TextDecoder().decode(decoded[0].slice(0, 8))).toBe("OpusHead");
    expect(new TextDecoder().decode(decoded[1].slice(0, 8))).toBe("OpusTags");
    expect(Array.from(decoded[2])).toEqual([...FRAME]);
  });

  it("ставит EOS, даже если аудио нет", () => {
    const head = OPUS_HEAD;
    const ogg = buildOgg(head, [] as AudioPacket[]);
    const pages = readPages(ogg);
    expect(pages.length).toBe(2);
    expect(pages[1].headerType & 0x04).toBe(0x04);
  });
});

describe("remuxWebmOpusToOgg", () => {
  it("возвращает Blob типа audio/ogg", async () => {
    const blob = new Blob([buildWebm() as unknown as BlobPart], { type: "audio/webm" });
    const out = await remuxWebmOpusToOgg(blob);
    expect(out.type).toBe("audio/ogg");
    const bytes = new Uint8Array(await out.arrayBuffer());
    expect(Array.from(bytes.slice(0, 4))).toEqual([0x4f, 0x67, 0x67, 0x53]);
  });
});

describe("pickRecorderFormat", () => {
  it("без MediaRecorder выбирает WebM с переупаковкой", () => {
    const fmt = pickRecorderFormat();
    expect(fmt.container).toBe("webm");
    expect(fmt.needRemux).toBe(true);
  });
});
