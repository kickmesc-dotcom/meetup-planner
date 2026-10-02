/**
 * Приведение записи из браузера к формату, который принимает Telegram.
 *
 * Telegram `sendVoice` понимает только OGG/OPUS (.ogg), MP3 (.mp3) и M4A (.m4a).
 * Chrome и, значит, Telegram-веб пишут WebM/OPUS — такой файл Telegram отбивает
 * («audio must be in an .OGG file encoded with OPUS»). Поэтому:
 *
 *  1) где браузер умеет писать OGG/OPUS (Firefox) — пишем сразу OGG;
 *  2) где умеет M4A (Safari / часть Chrome) — отдаём M4A как есть;
 *  3) иначе (Chrome WebM) — переупаковываем WebM→OGG прямо на клиенте.
 *
 * Переупаковка НЕ декодирует звук: Opus-пакеты в WebM и в OGG идентичны, меняется
 * только контейнер (EBML → Ogg). Поэтому не нужны ни WASM, ни серверный ffmpeg.
 * Это вынужденная мера: OGG-писателя в браузере нет, а Telegram требует именно
 * OGG-контейнер.
 */

export type VoiceContainer = "ogg" | "m4a" | "mp3" | "webm";

export interface RecorderFormat {
  /** mimeType для `new MediaRecorder(stream, { mimeType })`. */
  mimeType: string;
  container: VoiceContainer;
  /** true — запись надо переупаковать в OGG перед отправкой. */
  needRemux: boolean;
}

// Порядок кандидатов: сначала форматы, которые Telegram принимает как есть.
// WebM — последний: его придётся переупаковывать.
const CANDIDATES: Array<{ mime: string; container: VoiceContainer }> = [
  { mime: "audio/ogg;codecs=opus", container: "ogg" },
  { mime: "audio/ogg", container: "ogg" },
  { mime: "audio/mp4;codecs=mp4a.40.2", container: "m4a" },
  { mime: "audio/mp4", container: "m4a" },
  { mime: "audio/webm;codecs=opus", container: "webm" },
  { mime: "audio/webm", container: "webm" },
];

/** Выбрать лучший поддерживаемый формат записи (см. порядок выше). */
export function pickRecorderFormat(): RecorderFormat {
  if (
    typeof MediaRecorder !== "undefined" &&
    typeof MediaRecorder.isTypeSupported === "function"
  ) {
    for (const c of CANDIDATES) {
      if (MediaRecorder.isTypeSupported(c.mime)) {
        return {
          mimeType: c.mime,
          container: c.container,
          needRemux: c.container === "webm",
        };
      }
    }
  }
  // Без MediaRecorder.isTypeSupported доверяем дефолту браузера (это Chrome →
  // WebM), поэтому переупаковываем.
  return { mimeType: "", container: "webm", needRemux: true };
}

// ---------------------------------------------------------------------------
// EBML / WebM разбор
// ---------------------------------------------------------------------------

// Известные ID элементов (значения, а не смещения — сравниваем как есть).
const ID_EBML = 0x1a45dfa3;
const ID_SEGMENT = 0x18538067;
const ID_INFO = 0x1549a966;
const ID_TIMESTAMP_SCALE = 0x2ad7b1;
const ID_TRACKS = 0x1654ae6b;
const ID_TRACK_ENTRY = 0xae;
const ID_CODEC_ID = 0x86;
const ID_CODEC_PRIVATE = 0x63a2;
const ID_AUDIO = 0xe1;
const ID_SAMPLING_FREQ = 0xb5;
const ID_CHANNELS = 0x9f;
const ID_CLUSTER = 0x1f43b675;
const ID_TIMESTAMP = 0xe7;
const ID_SIMPLE_BLOCK = 0xa3;
const ID_BLOCK_GROUP = 0xa0;
const ID_BLOCK = 0xa1;
const ID_VOID = 0xec;

// Элементы уровня Segment: по ним понимаем, что кластер без известного размера
// закончился и начался следующий элемент.
const SEGMENT_LEVEL = new Set<number>([
  0x114d9b74, // SeekHead
  ID_INFO,
  ID_TRACKS,
  ID_CLUSTER,
  0x1c53bb6b, // Cues
  0x1043a770, // Chapters
  0x1941a469, // Attachments
  0x1254c367, // Tags
  ID_VOID,
]);

export interface AudioPacket {
  data: Uint8Array;
  /** Granule в сэмплах 48 кГц (сколько сэмплов декодировано к концу пакета). */
  granule: number;
}

export interface ParsedOpus {
  /** OpusHead из CodecPrivate (или синтезированный). */
  head: Uint8Array;
  packets: AudioPacket[];
}

function vintLength(first: number): number {
  for (let i = 0; i < 8; i++) {
    if (first & (0x80 >> i)) return i + 1;
  }
  return 0;
}

interface Element {
  id: number;
  /** Позиция сразу после ID+размер (начало содержимого). */
  next: number;
  size: number;
  unknown: boolean;
  /** Позиция сразу после размера (то же, что next). */
  dataStart: number;
}

function readElementId(view: DataView, pos: number): { id: number; next: number } {
  const len = vintLength(view.getUint8(pos));
  if (len === 0) throw new Error("bad_ebml_id");
  let id = 0;
  for (let i = 0; i < len; i++) id = id * 256 + view.getUint8(pos + i);
  return { id, next: pos + len };
}

function readElement(view: DataView, pos: number): Element {
  const { id, next } = readElementId(view, pos);
  const first = view.getUint8(next);
  const len = vintLength(first);
  if (len === 0) throw new Error("bad_ebml_size");
  const mask = (1 << (8 - len)) - 1;
  let size = first & mask;
  for (let i = 1; i < len; i++) size = size * 256 + view.getUint8(next + i);
  const unknown = size === Math.pow(2, 7 * len) - 1;
  const dataStart = next + len;
  return { id, next: dataStart, dataStart, size, unknown };
}

function readUint(view: DataView, start: number, end: number): number {
  let v = 0;
  for (let i = start; i < end; i++) v = v * 256 + view.getUint8(i);
  return v;
}

function readAscii(bytes: Uint8Array, start: number, end: number): string {
  let s = "";
  for (let i = start; i < end; i++) s += String.fromCharCode(bytes[i]);
  return s;
}

function vintValue(bytes: Uint8Array, pos: number, len: number): number {
  let v = bytes[pos] & ((1 << (8 - len)) - 1);
  for (let i = 1; i < len; i++) v = v * 256 + bytes[pos + i];
  return v;
}

/** Длительность Opus-кадра в сэмплах (48 кГц) по TOC-байту. */
function opusFrameSamples(toc: number): number {
  const config = toc >> 3;
  const c = toc & 0x03;
  if (config >= 16) return [120, 240, 480, 960][c]; // CELT 2.5 / 5 / 10 / 20 мс
  if (config >= 12) return [480, 960, 480, 960][c]; // Hybrid 10 / 20 мс
  return [480, 960, 1920, 2880][c]; // SILK 10 / 20 / 40 / 60 мс
}

function splitLacing(payload: Uint8Array, lacing: number): Uint8Array[] {
  if (lacing === 0) return [payload];
  const count = payload[0];
  const frames: Uint8Array[] = [];
  let o = 1;
  if (lacing === 2) {
    // Фиксированный размер.
    const n = count + 1;
    const size = (payload.length - 1) / n;
    for (let i = 0; i < n; i++) {
      frames.push(payload.subarray(o, o + size));
      o += size;
    }
  } else if (lacing === 1) {
    // Xiph: размеры через 255-дополнение.
    const sizes: number[] = [];
    for (let i = 0; i < count; i++) {
      let size = 0;
      let b = 0;
      do {
        b = payload[o++];
        size += b;
      } while (b === 255);
      sizes.push(size);
    }
    for (let i = 0; i < count; i++) {
      frames.push(payload.subarray(o, o + sizes[i]));
      o += sizes[i];
    }
    frames.push(payload.subarray(o));
  } else {
    // EBML: размеры как vint.
    const sizes: number[] = [];
    for (let i = 0; i < count; i++) {
      const l = vintLength(payload[o]);
      sizes.push(vintValue(payload, o, l));
      o += l;
    }
    for (let i = 0; i < count; i++) {
      frames.push(payload.subarray(o, o + sizes[i]));
      o += sizes[i];
    }
    frames.push(payload.subarray(o));
  }
  return frames;
}

function parseBlockPayload(
  view: DataView,
  bytes: Uint8Array,
  start: number,
  end: number,
  clusterTs: number,
  scaleNs: number,
  out: AudioPacket[],
): void {
  if (end - start < 4) return;
  const tl = vintLength(bytes[start]);
  const rel = view.getInt16(start + tl, false);
  const flags = bytes[start + tl + 2];
  const lacing = (flags & 0x06) >> 1;
  const startSamples = Math.max(0, Math.round(((clusterTs + rel) * scaleNs) / 1e6 * 48));
  const frames = splitLacing(bytes.subarray(start + tl + 3, end), lacing);
  let granule = startSamples;
  for (const frame of frames) {
    if (frame.length === 0) continue;
    granule += opusFrameSamples(frame[0]);
    out.push({ data: frame, granule });
  }
}

function parseCluster(
  view: DataView,
  bytes: Uint8Array,
  start: number,
  end: number,
  scaleNs: number,
  out: AudioPacket[],
): number {
  let p = start;
  let ts = 0;
  while (p < end) {
    const el = readElementId(view, p);
    // Кластер без размера закончился — дальше начинается элемент уровня Segment.
    if (SEGMENT_LEVEL.has(el.id) && el.id !== ID_VOID) break;
    const sz = readElement(view, p);
    const dStart = sz.dataStart;
    const dEnd = sz.unknown ? end : Math.min(end, dStart + sz.size);
    if (el.id === ID_TIMESTAMP) {
      ts = readUint(view, dStart, dEnd);
    } else if (el.id === ID_SIMPLE_BLOCK) {
      parseBlockPayload(view, bytes, dStart, dEnd, ts, scaleNs, out);
    } else if (el.id === ID_BLOCK_GROUP) {
      const block = readElement(view, dStart);
      if (block.id === ID_BLOCK && !block.unknown) {
        parseBlockPayload(
          view,
          bytes,
          block.dataStart,
          Math.min(dEnd, block.dataStart + block.size),
          ts,
          scaleNs,
          out,
        );
      }
    }
    p = dEnd;
  }
  return p;
}

interface TrackInfo {
  codec: string;
  head: Uint8Array | null;
  channels: number;
  sampleRate: number;
}

function parseTrackEntry(
  view: DataView,
  bytes: Uint8Array,
  start: number,
  end: number,
): TrackInfo {
  const info: TrackInfo = { codec: "", head: null, channels: 1, sampleRate: 48000 };
  let p = start;
  while (p < end) {
    const el = readElement(view, p);
    const dStart = el.dataStart;
    const dEnd = el.unknown ? end : Math.min(end, dStart + el.size);
    if (el.id === ID_CODEC_ID) info.codec = readAscii(bytes, dStart, dEnd);
    else if (el.id === ID_CODEC_PRIVATE) info.head = bytes.slice(dStart, dEnd);
    else if (el.id === ID_AUDIO) {
      let q = dStart;
      while (q < dEnd) {
        const sub = readElement(view, q);
        const sEnd = sub.unknown ? dEnd : Math.min(dEnd, sub.dataStart + sub.size);
        if (sub.id === ID_CHANNELS) info.channels = readUint(view, sub.dataStart, sEnd);
        else if (sub.id === ID_SAMPLING_FREQ) {
          info.sampleRate = Math.round(view.getFloat64(sub.dataStart, false));
        }
        q = sEnd;
      }
    }
    p = dEnd;
  }
  return info;
}

function parseTracks(
  view: DataView,
  bytes: Uint8Array,
  start: number,
  end: number,
): TrackInfo | null {
  let p = start;
  while (p < end) {
    const el = readElement(view, p);
    if (el.unknown) break;
    const dEnd = Math.min(end, el.dataStart + el.size);
    if (el.id === ID_TRACK_ENTRY) {
      const info = parseTrackEntry(view, bytes, el.dataStart, dEnd);
      if (info.codec.startsWith("A_OPUS")) return info;
    }
    p = dEnd;
  }
  return null;
}

function synthesizeOpusHead(channels: number, sampleRate: number): Uint8Array {
  const b = new Uint8Array(19);
  const tag = "OpusHead";
  for (let i = 0; i < tag.length; i++) b[i] = tag.charCodeAt(i);
  b[8] = 1;
  b[9] = Math.max(1, Math.min(255, channels));
  const sr = sampleRate || 48000;
  b[12] = sr & 0xff;
  b[13] = (sr >> 8) & 0xff;
  b[14] = (sr >> 16) & 0xff;
  b[15] = (sr >> 24) & 0xff;
  return b;
}

/** Разобрать WebM/Opus: вытащить OpusHead и аудио-пакеты с гранулами. */
export function parseWebmOpus(buffer: ArrayBuffer): ParsedOpus {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 8) throw new Error("empty_webm");
  const ebml = readElement(view, 0);
  if (ebml.id !== ID_EBML) throw new Error("not_webm");
  let pos = ebml.unknown ? 0 : ebml.dataStart + ebml.size;
  const seg = readElement(view, pos);
  if (seg.id !== ID_SEGMENT) throw new Error("no_segment");
  const segStart = seg.dataStart;
  const segEnd = seg.unknown
    ? bytes.length
    : Math.min(bytes.length, segStart + seg.size);

  let scaleNs = 1_000_000;
  let track: TrackInfo | null = null;
  const packets: AudioPacket[] = [];

  let p = segStart;
  while (p < segEnd) {
    const el = readElement(view, p);
    const dStart = el.dataStart;
    const dEnd = el.unknown ? segEnd : Math.min(segEnd, dStart + el.size);
    if (el.id === ID_INFO) {
      let q = dStart;
      while (q < dEnd) {
        const sub = readElement(view, q);
        const sEnd = sub.unknown ? dEnd : Math.min(dEnd, sub.dataStart + sub.size);
        if (sub.id === ID_TIMESTAMP_SCALE) scaleNs = readUint(view, sub.dataStart, sEnd);
        q = sEnd;
      }
    } else if (el.id === ID_TRACKS) {
      track = parseTracks(view, bytes, dStart, dEnd) ?? track;
    } else if (el.id === ID_CLUSTER) {
      const next = parseCluster(view, bytes, dStart, dEnd, scaleNs, packets);
      if (el.unknown) {
        p = next > p ? next : segEnd;
        continue;
      }
    }
    p = dEnd;
  }

  if (track === null) throw new Error("no_opus_track");
  const head = track.head ?? synthesizeOpusHead(track.channels, track.sampleRate);
  return { head, packets };
}

// ---------------------------------------------------------------------------
// Ogg-писатель
// ---------------------------------------------------------------------------

// CRC-таблица Ogg: полином 0x04c11db7, без отражения, начальное значение 0.
const OGG_CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n << 24;
    for (let k = 0; k < 8; k++) {
      c = c & 0x80000000 ? ((c << 1) ^ 0x04c11db7) >>> 0 : (c << 1) >>> 0;
    }
    t[n] = c >>> 0;
  }
  return t;
})();

/** CRC страницы Ogg (используется в её заголовке). */
export function oggCrc(bytes: Uint8Array): number {
  let crc = 0;
  for (let i = 0; i < bytes.length; i++) {
    crc = ((crc << 8) ^ OGG_CRC_TABLE[((crc >>> 24) & 0xff) ^ bytes[i]]) >>> 0;
  }
  return crc >>> 0;
}

function writeInt64LE(view: DataView, off: number, value: number): void {
  const lo = value >>> 0;
  const hi = Math.floor(value / 0x100000000) >>> 0;
  view.setUint32(off, lo, true);
  view.setUint32(off + 4, hi, true);
}

/** Собрать одну страницу Ogg из пакетов (каждый пакет — целое число сегментов). */
export function buildOggPage(
  packets: Uint8Array[],
  granule: number,
  serial: number,
  sequence: number,
  headerType: number,
): Uint8Array {
  const laces: number[] = [];
  for (const pkt of packets) {
    let len = pkt.length;
    while (len >= 255) {
      laces.push(255);
      len -= 255;
    }
    laces.push(len);
  }
  let bodyLen = 0;
  for (const pkt of packets) bodyLen += pkt.length;
  const headerLen = 27 + laces.length;
  const out = new Uint8Array(headerLen + bodyLen);
  const view = new DataView(out.buffer);
  out[0] = 0x4f;
  out[1] = 0x67;
  out[2] = 0x67;
  out[3] = 0x53; // OggS
  out[4] = 0; // version
  out[5] = headerType & 0xff;
  writeInt64LE(view, 6, granule);
  view.setUint32(14, serial, true);
  view.setUint32(18, sequence, true);
  view.setUint32(22, 0, true); // checksum — заполним после
  out[26] = laces.length;
  for (let i = 0; i < laces.length; i++) out[27 + i] = laces[i];
  let o = headerLen;
  for (const pkt of packets) {
    out.set(pkt, o);
    o += pkt.length;
  }
  view.setUint32(22, oggCrc(out), true);
  return out;
}

function encodeAscii(s: string): Uint8Array {
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

function buildOpusTags(): Uint8Array {
  const vendor = encodeAscii("ghg-mini-app");
  const out = new Uint8Array(8 + 4 + vendor.length + 4);
  out.set(encodeAscii("OpusTags"), 0);
  const view = new DataView(out.buffer);
  view.setUint32(8, vendor.length, true);
  out.set(vendor, 12);
  view.setUint32(12 + vendor.length, 0, true);
  return out;
}

function concatBytes(parts: Uint8Array[]): Uint8Array {
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

/** Собрать полноценный Ogg/Opus поток из OpusHead и аудио-пакетов. */
export function buildOgg(head: Uint8Array, packets: AudioPacket[]): Uint8Array {
  const serial = (Math.random() * 0xffffffff) >>> 0;
  const pages: Uint8Array[] = [];
  let seq = 0;
  // Первая страница — только OpusHead, флаг BOS (0x02), granule 0.
  pages.push(buildOggPage([head], 0, serial, seq++, 0x02));
  // Вторая — OpusTags (минимальный, без комментариев).
  const tags = buildOpusTags();

  const groups: AudioPacket[][] = [];
  let current: AudioPacket[] = [];
  let size = 0;
  for (const pk of packets) {
    if (current.length > 0 && (current.length >= 64 || size + pk.data.length > 4096)) {
      groups.push(current);
      current = [];
      size = 0;
    }
    current.push(pk);
    size += pk.data.length;
  }
  if (current.length > 0) groups.push(current);

  if (groups.length === 0) {
    pages.push(buildOggPage([tags], 0, serial, seq++, 0x04));
  } else {
    pages.push(buildOggPage([tags], 0, serial, seq++, 0x00));
    groups.forEach((g, idx) => {
      const last = g[g.length - 1];
      const isLast = idx === groups.length - 1;
      pages.push(
        buildOggPage(
          g.map((x) => x.data),
          last.granule,
          serial,
          seq++,
          isLast ? 0x04 : 0x00,
        ),
      );
    });
  }
  return concatBytes(pages);
}

// ---------------------------------------------------------------------------
// Публичный API
// ---------------------------------------------------------------------------

/** WebM/Opus → Ogg/Opus. Бросает Error, если запись не распознана как WebM/Opus. */
export async function remuxWebmOpusToOgg(blob: Blob): Promise<Blob> {
  const buffer = await blob.arrayBuffer();
  const { head, packets } = parseWebmOpus(buffer);
  if (packets.length === 0) throw new Error("no_audio");
  const ogg = buildOgg(head, packets) as unknown as BlobPart;
  return new Blob([ogg], { type: "audio/ogg" });
}

/**
 * Подготовить запись к отправке: при необходимости переупаковать в OGG и дать
 * правильное имя файла (Telegram определяет формат в том числе по расширению).
 */
export async function prepareVoiceBlob(
  blob: Blob,
  fmt: RecorderFormat,
): Promise<{ blob: Blob; filename: string; container: VoiceContainer }> {
  if (fmt.needRemux) {
    const ogg = await remuxWebmOpusToOgg(blob);
    return { blob: ogg, filename: "voice.ogg", container: "ogg" };
  }
  return { blob, filename: `voice.${fmt.container}`, container: fmt.container };
}
