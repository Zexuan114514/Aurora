# Textractor issue draft（可直接粘到 GitHub）

> 仓库：https://github.com/Artikash/Textractor/issues
> 标题建议：**No hooks fire on Emote/Artemis x64 engine (e.g. Amakano 3) — engine rasterizes text itself; workaround + suggestions**

## Body

### Environment

- Windows 11 x64, Textractor release build, both `x86\TextractorCLI.exe` and `x64\TextractorCLI.exe` tested.
- Game: **アマカノ３ / Amakano 3** (Azarashi Soft), 64-bit, launched with Locale Emulator.
- Game files: `Amakano3.exe` (5.2 MB) + `emotedriver.dll` (33 MB) + `iarsys64.dll`.

### Problem

Attaching works (`Textractor: 管道已连接` / "pipe connected", process hijacked, 40+ generic GDI hooks
injected), but **no thread ever produces text** — advancing the dialogue for minutes yields 0 lines.
There is also no engine hook attempt at all: the x64 CLI prints **no `vnreng:` lines** in this game.

### Diagnosis

1. `emotedriver.dll` **imports only `KERNEL32.dll` and `D3DCOMPILER_47.dll`** — the engine rasterizes
   glyphs itself and submits geometry with **D3D11** (`Amakano3.exe` imports `d3d11.dll`,
   `D3DCOMPILER_47.dll`, `emotedriver.dll`; GDI32 is imported for window/UI purposes only).
2. Consequently `TextOutW` / `ExtTextOutW` / `GetGlyphOutlineW` are **never called for dialogue**
   → every generic text hook is dead by design, not by mis-injection.
   (Raw hook dumps confirm 0 content lines while the text box is visibly updating.)
3. The x64 `TextractorCLI.exe` / `texthook.dll` contain no Artemis/Emote engine hook (checked the
   binaries for `Artemis`/`Emote` strings), so there is nothing to pick manually either.
   Note LunaHook ships `engine64/Artemis.cpp`, so the engine *is* hookable in principle.

### Workaround that works (verified on this game)

Plain user hooks with an explicit address — the dialogue text is passed as a **UTF-8 string**
(`S` + `65001#`), so `Q`/UTF-16 codes will not work here:

```
HS65001#-6C@1401B1F70                      -> as module+RVA: HS65001#-6C@1B1F70:Amakano3.exe
HS65001#20@38A78:emotedriver.dll
```

Both extract the dialogue perfectly (`義大「そうだな」`, `詩夢を抱きしめる腕に、力を込める。`, …).
The first one was found with MisakaHookFinder; the second one was found independently by a
sampling-based candidate harvester we wrote for our launcher.

### Suggestions

1. **Add an Emote/Artemis x64 engine hook.** The text function is reachable at a stable RVA in this
   build (`+0x1B1F70` in the exe, `+0x38A78` in `emotedriver.dll`); a signature search on the
   surrounding prologue should give a generic hook for this engine family, which currently requires
   a manual code for every title.
2. **Expose the hook search through `TextractorCLI`.** `SearchForHooks`/`SearchForText` are only
   reachable from the GUI today (the CLI accepts just `attach|detach|hookcode`), so headless tools
   and launchers cannot offer the feature that makes hard engines tractable.
3. **Make the search cheaper.** `SearchForHooks` MH-hooks thousands of addresses at once, which
   makes the game stutter/flicker for the whole search window. Harvesting candidate
   `(code address, stack offset, string)` triples by **sampling thread stacks**
   (SuspendThread → GetThreadContext → scan `[ESP-0x100, ESP+0x100]`, treat each slot as a string
   pointer) is read-only, causes no stutter, and produced a working code in ~12 s on this game.
   The "which candidate is the real line" decision can also be automated by comparing each sampled
   string with the current on-screen text.
4. **Document the negative-offset adjustment.** `host/hookcode.cpp` does
   `if (hp.offset < 0) hp.offset -= 4;` for ITH compatibility. That means a *measured* stack offset
   of `-0x70` has to be written as `-6C` (exactly the code above). This is a real footgun when
   hand-writing codes from a debugger; a note in the README/H-code docs would save a lot of time.
5. **Minor: the user hook code is echoed into the text stream.** Sending
   `HS65001#-6C@1B1F70:Amakano3.exe` makes the CLI emit `HS65001#-6C@1401B1F70` as if it were a line
   of game text; downstream consumers have to filter it out.
6. **Minor: hook codes may contain `:`** (e.g. `...@1B1F70:Amakano3.exe`). Tools that split the
   `[handle:pid:addr:ctx:ctx2:name:code]` line naively break; documenting that the code field may
   itself contain colons (parse with at most 6 splits) would help.

I'm happy to test a build with an Emote hook and provide raw dumps / the two working codes above.
