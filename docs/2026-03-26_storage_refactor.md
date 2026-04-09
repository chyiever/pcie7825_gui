# 2026-03-26 Storage Refactor

## 1. Current Storage Behavior

As of 2026-03-26, the storage path has the following behavior:

- Storage uses a dedicated worker thread: `StorageWorker`
- Acquisition pushes binary `StorageBlock` objects into a queue
- The worker appends directly into `.bin` files
- The program does **not** generate sidecar `.json` files anymore
- File naming uses the first stored block's acquisition start time
- File number is 7 digits with zero padding
- Filename prefix is `fs-eDAS`

Filename format:

```text
{seq:07d}-fs-eDAS-{scan_rate:04d}Hz-{points:04d}pt-{timestamp}.{ms}.bin
```

Example:

```text
0000043-fs-eDAS-100000Hz-0069pt-20260326T090106.810.bin
```

## 2. File Duration Semantics

`Frames/File` is frame-based, not second-based.

The effective duration of one file is:

```text
file_duration_s = Frames * Frames/File / scan_rate
```

Example:

- `Frames = 2000`
- `Frames/File = 50`
- `scan_rate = 100000`

Then:

```text
2000 * 50 / 100000 = 1 s
```

So this configuration produces roughly one file per second.

If you want `10 s` per file under the same scan rate and frame size:

- keep `Frames = 2000`
- set `Frames/File = 500`

## 3. Streaming Write Strategy

The system no longer waits for a full file worth of data before writing.

Instead:

- acquisition accumulates data in memory by storage chunks
- storage chunks are written incrementally by the worker thread
- for phase mode, file rotation is based on `target_frames_per_file`
- chunked writes reduce UI stalls compared with end-of-file bulk writes

Current rotation logic:

- `target_frames_per_file = Frames * Frames/File`
- `record.frame_count >= target_frames_per_file` triggers rotation

## 4. Phase Storage Rules

For phase data, storage now uses the **actual frame count returned by the driver**, not the requested frame count.

This is important because the DLL returns `points_returned`, and the true stored frame count is derived from:

```text
actual_frames = points_returned / fbg_num_per_ch
```

The following items now use `actual_frames`:

- `frames_in_block`
- `frame_count` accumulation
- file rotation accounting
- acquisition frame counter
- estimated block start timestamp used in the filename

This avoids duration errors when the hardware returns fewer or more frames than requested.

## 5. What Was Removed

The following old behavior is no longer valid:

- `.bin + .json` paired output
- manifest sidecar files
- treating `Frames/File` as seconds per file

## 6. Verification Notes

Observed logs now match the expected formula.

For example, in phase mode with:

- `scan_rate = 100000`
- `Frames = 2000`
- `Frames/File = 50`

logs show:

```text
Completed storage file ... with 100000 frames in 50 blocks
```

Since `100000 frames / 100000 Hz = 1 s`, the generated files are 1-second files, which matches the configuration.
