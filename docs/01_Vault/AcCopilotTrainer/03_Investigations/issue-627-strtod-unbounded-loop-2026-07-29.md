---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-29
updated: 2026-07-29
topic: "#627 wedge mechanism — the loop is a decimal→float parser, not a float→decimal printer"
source_type: repo
related_issues: [627]
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/rig-freeze-csp-init-livelock-2026-07-17.md
  - AcCopilotTrainer/03_Investigations/issue-628-acpmf-corpse-classify-2026-07-19.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #627: the wedge loop is a decimal→float parser with a data-conditional termination variable

Static analysis of the exact module the live RIP samples attributed, done offline (no rig time).
This **corrects the direction** recorded in #627's v2 reconciliation and in the upstream report,
and it names the specific unbounded loop.

## Module identity — verified, not assumed

| field | value |
|---|---|
| path | `C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\dwrite.dll` |
| `OriginalFilename` | `accRenderingAdv.dll` |
| `FileVersion` | `0.2.11.0` |
| SHA256 | `6546FDF7854213DCC87A0B2BCB68155BEBCC0D7892D3BECB5795F310CBF24C6E` |
| ImageBase | `0x180000000`, SizeOfImage `0x2187000` |

The SHA256 **matches the one filed upstream** in
[acc-extension-config#622](https://github.com/ac-custom-shaders-patch/acc-extension-config/issues/622),
so the RVAs in that report and in this node address the same bytes.

## Correction: the direction was inverted

#627 §3.5's v2 correction reads *"a float→decimal formatting loop (Dragon4-style)"*. The bytes say
the opposite — this is a **decimal-string → binary-double conversion** (a `strtod` core):

- It reads **ASCII** from `[rcx]`, tests bytes against `'.'` (`0x2E`) and `'0'` (`0x30`), and
  converts with `and al, 0xF` (ASCII digit → value).
- It packs digit pairs: `shl al,2; add dl,al; add dl,dl; add dl,r8b` = `d1*10 + d2`.
- It ends at `cvtsi2sd xmm0, rdx` (`0x14E703C`) — integer → double — or tail-calls
  `0x14E7360` with (mantissa `rcx`, out-ptr `rdx`, binary exponent `r8d`, sign `r9d`).
- On decimal-exponent overflow it writes the **±inf** bit patterns directly:
  `movabs rax, 0xFFF0000000000000` / `0x7FF0000000000000`, `cmove` on the sign (`0x14E707B`).
- The digit-count thresholds are textbook `strtod`: `cmp ebx, 0x12` (18) and `cmp ebx, 0x14` (20)
  around the 64-bit-mantissa fast path (2^63 ≈ 9.22e18 = 19 digits), with `0x320` (800) as the
  long-input cutoff.

`0x147B` is confirmed as the ÷100 reciprocal (`(x>>2) * 0x147B >> 0x11` ≈ `x/100`), consistent with
the existing AGENTS.md Tier-1 note. What changes is **which way the conversion runs** — and that
matters, because a parser's input is a **string we can go and find**, whereas a printer's input is a
transient float.

## The unbounded loop — mechanism, from the control flow

Live RIP sampling put three of eight samples at `0x14E70F4`, `0x14E714F`, `0x14E7169`. All three are
inside **one** loop, the ÷100 normalization loop `0x14E70E0 … 0x14E71C5`:

```text
0x14E70D1  cmp r11d, 9         ; r11d = decimal exponent
0x14E70D5  jge 0x14E71CB       ; ... else enter the loop
0x14E70E0  loop head           ; <<< RIP sample at 0x14E70F4
0x14E70E6  and eax, 0x1FF      ; eax = (r10d - r8d) & 511 = live limb count
0x14E70EE  jge 0x14E7271       ; EXIT 2: r11d >= limb count
   ...     inner limb walk, ÷100 per limb   ; <<< RIP samples at 0x14E714F, 0x14E7169
0x14E716E  test ebx, ebx
0x14E7170  je  0x14E71C1       ; carry-out digit is ZERO -> SKIP the increment
0x14E71BE  inc r11d            ; the ONLY progress toward EXIT 1
0x14E71C1  cmp r11d, 9
0x14E71C5  jl  0x14E70E0       ; BACKEDGE
```

**The loop's progress variable is incremented conditionally on data.** There is no iteration cap.
Both exits depend on quantities the loop body itself computes:

- **Exit 1** needs `r11d` to reach 9 — but `inc r11d` is skipped whenever the ÷100 step carries out
  a zero digit (`ebx == 0`).
- **Exit 2** needs the live limb count to shrink to `r11d` — which requires the top limb to become
  zero (`cmove r10d, r9d` at `0x14E7138`).

So the loop fails to terminate exactly when **`ebx == 0` on every pass while the top limb never
zeroes** — a non-decreasing fixed point. The body still does full work each pass (a walk of up to
512 limbs with two `imul 0x147B` per limb), which is precisely the measured signature: a sustained
**2.87e9–2.88e9 cycles/s full-core burn** with a **bounded RIP footprint** spanning the two ÷100
sites, while `acpmf_graphics.packetId` stays pinned and physics keeps advancing.

The sibling ×100 loop (`0x14E71E0 … 0x14E726B`) has the mirror hazard: its `dec r11d`
(`0x14E721C`) is likewise conditional, with backedge `cmp r11d, 9; jg`.

## How an out-of-domain limb becomes reachable (plausible, NOT yet confirmed)

Stated as a hypothesis with its confidence explicit, because the honest bar in this saga is a
measured trigger, not a coherent story:

The scaling loops treat each limb byte as a **6-bit** value (`and edx, 0x3F`, `shl edx, 6`,
`shr eax, 6`). The digit-packing phase writes `d1*10 + d2`, and it converts bytes with
`and al, 0xF` **without any digit validation** — only `'.'` is special-cased. For real digits that
yields 0…99; for a **non-digit byte** it yields up to `15*10+15 = 165`. A limb outside the intended
domain makes the ÷100 magic compute a quotient that need not reduce the value, which is the
fixed-point condition above.

That path requires the caller to hand this routine a buffer whose digit count and contents disagree
(a stray byte, a non-terminated buffer, a reused scratch buffer) — normal for a CRT-internal core
whose contract puts validation in the caller.

**Confidence:** the loop being structurally unbounded with a data-conditional progress variable is
**established from the bytes**. The specific out-of-domain trigger is **plausible and untested**.

## Why this is a materially better upstream report

It moves the report from *"RIPs land in a formatting region"* to *"here is the loop, here is its
termination variable, here is why it can fail to advance, and here is the input class that would do
it"* — actionable without the maintainer reproducing anything, and with an obvious defensive fix on
their side (cap the iteration count, or validate the limb domain).

## Follow-through owned under #627 (no new issues, per operator directive)

1. **Name the input.** Extend the shipped forensics instrument so that when a wedge RIP lands in this
   loop, it reads the wedged thread's stack limb buffer at `rsp+0x20` (512 bytes) and decodes the
   digits — turning "plausible trigger" into a named value. The decode is a pure function, so it is
   unit-testable off-rig.
2. **Correct the upstream report** (operator-gated: outward-facing) with the inverted direction and
   the loop analysis.
3. **Business capability** stays the deliverable of record: the rig must run real coaching sessions
   through the shipped path regardless of whether CSP ever fixes this.

## Reproduce the analysis

The analyzed DLL is operator-owned game content and is not redistributable, so the checked-in
procedure verifies its recorded hash before disassembling the exact RVA range. Run this on the rig
after installing the two analysis-only packages (`py -m pip install capstone pefile`):

```powershell
@'
from hashlib import sha256
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_64, Cs
import pefile

module = Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\dwrite.dll")
expected = "".join(
    ("6546FDF7", "854213DC", "C87A0B2B", "CB68155B", "EBCC0D78", "92D3BECB", "5795F310", "CBF24C6E")
).lower()
actual = sha256(module.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit(f"refusing a different module: expected {expected}, got {actual}")

start_rva, stop_rva = 0x14E6DB0, 0x14E7355
pe = pefile.PE(str(module), fast_load=True)
code = pe.get_data(start_rva, stop_rva - start_rva)
decoder = Cs(CS_ARCH_X86, CS_MODE_64)
for instruction in decoder.disasm(code, start_rva):
    print(f"0x{instruction.address:08X}  {instruction.mnemonic:<8} {instruction.op_str}")
'@ | py -
```

The output must cover `0x14E70E0…0x14E71C5` and show the conditional `inc r11d` /
`cmp r11d, 9` / backward `jl` sequence reproduced above.
