# QIJUZHU · DAYBOOK

> **Version note:** v3.0 is a single-machine prototype for a local plain-text memory workflow. Concurrency recovery, permission control, identity authorization, and formal enterprise stress testing have not been completed.

## Three numbers

| Number | Meaning |
|---|---|
| **365,000 entries · about 3.7 s** | median full-index time in repeat runs on a synthetic volume; see report for conditions |
| **1,000,000 entries · append in 0.281 s** | recorded incremental-append result; not a fixed time for every machine |
| **600 writes · zero interleaving** | 20 processes appending to the same volume; every entry intact |

These measurements cover indexing, appending, and concurrent writes; results depend on the test environment and workload.

Reproduce the 365,000-entry synthetic-volume benchmark with [test/benchmark_365k.py](test/benchmark_365k.py). Results depend on the target machine and run conditions.

The final documentation-check rerun took 3.610 / 3.677 / 3.745 seconds, with a 3.677-second median. The data was read immediately after generation (warm-cache result).

A plain-text journal whose source volumes remain readable with ordinary text editors.

> Your memory should not be a black box. It should be a stack of ledger pages you can flip through.

## What it is

A journal — an append-only text log — plus a one-pass scanner that turns it into an index.

Core indexing requires no database, server, network connection, or third-party Python package. Python 3 is required; the optional chatroom component runs an HTTP server.

## Why the name "Qijuzhu" (起居注)

For nearly two thousand years, Chinese court historians kept the *qijuzhu* — the day-by-day record of the emperor's own words and deeds. The name goes back to the Han dynasty (1st century AD); as a full institution it was formalized in the Tang, and such records were kept, on and off, until 1910.

It ran on four iron rules:

- **Append-only** — an entry, once written, was never altered.
- **Independent recorder** — the Tang ideal was that *even the emperor did not get to read it*. (The classical ideal, not a practice every dynasty kept — later courts did ask to look.)
- **Chronological** — "以事系日，以日系月，以月系时，以时系年": day by day, never reshuffled.
- **Source of record** — qijuzhu → veritable records → official history, three tiers.

Two thousand years of practice settled one point: **records that matter must be append-only, and independent of the one being recorded.**

We invented nothing. We just hung that two-thousand-year-old ledger on your AI.

## Install

Nothing to install. Copy the directory.

```
python3 daybook.py index     # build the index
python3 daybook.py watch     # watch volumes, re-index on change
sh daybook.sh 协作=sample/协作卷.txt   # same job, sh + awk only
```

## Measured performance

365,000 entries (1,000 a day for a year), 42.7 MB plain text, on a Mac.

| Implementation | Time | Entries |
|---|---|---|
| Python, before fix | > 180 s | not finished ✘ |
| **Python, after fix (historical single run)** | **2.84 s** | **365,000 ✔** |
| **sh + awk** | **5.19 s** | **365,000 ✔** |

At one million entries (54 MB, earlier benchmark):

| Case | Time |
|---|---|
| First full scan | 8.3 s |
| No change | 0.31 s |
| Append a few entries | 2.46 s |

Incremental indexing matters here. Since volumes are append-only, the index does not rescan.
A cursor file records byte size, mtime, resume offset and a probe hash.

Three cases:
- file unchanged ⇒ skip
- bytes appended ⇒ read only the tail, keep old index rows
- old bytes modified ⇒ report an **append-only violation** and rescan in full

## Multimodal: by reference, not by embedding

Images live in text as references:

```
![ink marker A](img/modou-01.png)
```

The image is a separate file. The text only records *where* it is. So:

- the text reads fine without the image
- the image can be replaced without touching the text
- **if the image is lost, the text is not corrupted**

This is the opposite of docx and pdf, which embed images inside the file. Corrupt one byte, or change format, and the picture may be gone.

**DAYBOOK uses plain-text volumes with references to separate image files. The text remains readable without those image files.**

## Both TXT and MD

Volumes are read by scanning lines against regular expressions, so the extension does not matter.
TXT, MD, log, rst, no extension — all work.

Markdown headings can also become entries:

```
[条目]
头正则=^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]
附头正则=^#{1,3}
字段=卷,行号,时间,类,标题,图数,层次

[规则]
类=tag:1
标题=tag:2
图数=count:![
层次=depth
```

## Customer-defined fields

Write a line in `daybook.conf` to add a column. Three built-ins: 卷, 行号, 时间.
Give each new field a rule:

```
field=tag:N        group N of the entry tag regex
field=len          character count of the entry body
field=count:X      occurrences of X in the body
field=contains:X   1 if body contains X else 0
field=depth        number of leading # (for Markdown headings)
```

No rule ⇒ the column stays empty (placeholder). Remove the name to drop the column.

## Author fields are not authentication

Entries can carry an author field according to the selected volume format. This field is a record value, not an authenticated identity.

## Source volumes and indexes

DAYBOOK keeps source volumes as plain text and builds indexes from them. The source files can be inspected with ordinary text tools, and indexes can be rebuilt from the volumes.

Portability and long-term readability still depend on the storage media, available software, encoding, and preservation practices. Plain text makes inspection easier; it does not guarantee permanent data preservation.

### Source volumes and the indexing tool

The index is derived data; the source volume is the record. This separation allows a user to inspect the source without DAYBOOK and rebuild an index when needed.

### Multiple volumes and read-through

Volumes can be indexed separately. The benchmark in this README measures local parsing and indexing on the stated test data; it does not guarantee that a particular AI model can read a volume in one prompt. Read-through limits depend on model context, tools, and hardware.

### Visible, portable files

Volumes can be stored at a user-chosen path and opened with standard text editors. Data location alone does not provide access control, backup, or protection from other tools that may transmit data.

## Five deployment considerations

This release is a single-machine prototype, not an enterprise-readiness claim. Concurrency recovery, permission control, identity authorization, and formal enterprise stress testing remain pending.

1. **Software cost** — core tools have no third-party Python package dependencies; hardware, storage, operations, and AI services may still incur costs.
2. **Inspectability** — source volumes are plain text; whether they meet specific audit, retention, or compliance requirements requires separate assessment.
3. **Local storage** — files can be configured locally; users must arrange backups separately. Copying files is not a validated backup strategy.
4. **Concurrent writes** — the project includes concurrent-append code and tests, but regular-file behavior depends on the operating system and filesystem; it is not a cross-platform standards guarantee.
5. **Failure recovery** — this version does not provide transaction logging or a power-loss recovery guarantee. Back up important data and validate recovery on the target environment.

Plain text and few dependencies provide inspectability and portability, but do not replace permission, backup, recovery, or compliance controls.

## Encoding

Detected automatically, never silently. Order: BOM → strict UTF-8 → GB18030 / Big5 / CP936 / Shift-JIS (accepted when the decoded CJK ratio exceeds 5%) → latin-1 fallback.
The detected encoding and the reason are written into the manifest.

## Design boundaries

The core tools are intentionally small and use standard library components. For current per-file line counts, see the bilingual README.

The design relies on existing system components but does not claim to provide:

**1. Storage** — no database engine is required. Source volumes are ordinary files; durability and recovery still depend on the filesystem, storage hardware, and backup practices.

**2. Concurrent append** — the writer uses `O_APPEND` and is tested under documented conditions. This does not establish a cross-platform atomicity or power-loss guarantee for regular files.

**3. History discipline** — append-only is a usage convention, not tamper-proof storage. Access controls, backups, and any required audit process must be provided separately.

## Intended scope

The implementation focuses on plain-text volumes, indexing, and local workflow support.

### Example uses

| User | How they use it |
|---|---|
| **Individual** | Diary, notes, and personal logs stored in text files |
| **Small teams evaluating a prototype** | Trial local logs and collaboration records after validating access and write behavior |
| **Regulated or legal workflows** | Assess retention, identity, access-control, integrity, and audit requirements separately; this prototype does not establish compliance |

### Operational considerations

- Core Python tools use the standard library.
- Local indexing does not require a database service.
- Python, operating systems, storage, and integrations still need maintenance and validation.

Plain-text source volumes can be inspected independently of the indexing program. Their preservation still depends on storage integrity and backups.

> Plain text and few dependencies can reduce some operational complexity; they do not eliminate maintenance or recovery responsibilities.

## Authors and contributors

**Lead author** — Originator and final arbiter. Set the direction, the bottom line ("never rewrite"), and the judgment.
　"Children must be disciplined, small trees must be pruned", "structure matters more than code" — both are the project's footing.

**Contributors** — Specification, criteria, audit, work orders. Does not touch production code.
　Wrote the main program, the concurrent writer, the sentinel, and all the measurements; also introduced every bug fixed today.

> Multiple lines review and refute each other; every criterion must come with numbers. No numbers, withdraw it. Numbers, record it.
> This system was not written by anyone. It was argued into existence.

> Everything here was done in a single day, 2026-10-05.

## License

MIT. See [`LICENSE`](LICENSE).

This package is one of the three in **daybook-suite**. The suite licenses **per file**, not per package; see [`LICENSING.md`](LICENSING.md).
