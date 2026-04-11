# chm-docs MCP Tool Feedback

Observations from real usage during Crestron lighting development (2026-04-07). Each section includes the actual call that failed and what the expected behavior should be.

## 1. Sub-object member resolution

**What happened:**
```
cross_reference_member("ClwDimuEx", "Level")
→ "S#Pro member 'Level' not found on ClwDimuEx"

cross_reference_member("ClwDimuEx", "LevelIn")
→ "S#Pro member 'LevelIn' not found on ClwDimuEx"
```

**Why it failed:** `Level` (UShortInputSig) and `LevelFeedback` (UShortOutputSig) live on `DimmingLoad`, accessed via `ClwDimuEx.DimmingLoads[1].Level`. Most lighting properties live on load sub-objects, not the device class itself.

**Expected behavior:** When a member isn't found on the device, traverse its typed collections (`DimmingLoads`, `SwitchedLoads`, `DinLoads`, `DinDimmableLoad`, `GlxxFlvDimmingLoad`, etc.) and check their element types. For `Level` on `ClwDimuEx`, the chain is: `ClwDimuEx.DimmingLoads` → `CrestronCollection<DimmingLoad>` → `DimmingLoad.Level`.

## 2. S#Pro class → SIMPL device name mapping

**What happened:**
```
cross_reference("ClwDimuEx")
→ "SIMPL Windows device not found for: ClwDimuEx"

cross_reference("CLW-DIMEX-P")
→ "Device not found in SIMPL Windows: CLW-DIMEX-P"

cross_reference("CLX-1DIM8")
→ "Device not found in SIMPL Windows: CLX-1DIM8"
```

**What worked:** `cross_reference("CLW-DIMUEX")` (had to guess the exact SIMPL model string).

**Expected behavior:** Accept S#Pro class names and fuzzy-match to SIMPL devices. The naming conventions are predictable:
- `ClwDimuEx` → `CLW-DIMUEX` or `CLW-DIMUEX-P`
- `Din1DimU4` → `DIN-1DIMU4`
- `Clx2DimU8` → `CLX-2DIMU8`
- `HzDimEx` → `HZ-DIMEX`

Also: CLW-DIMEX-P doesn't have its own SIMPL page but CLW-DIMUEX-P does. When a device isn't found, suggest close matches.

## 3. Truncated signal descriptions

**What happened:**
```
get_device_signals("CLW-DIMUEX-P")
→ Level_In: "Sets the light level. Valid analog values range from 0% (Off) to 100%. The en..."
```

**What was cut off:** "...entire range of values is accepted regardless of the specified min/max levels. If it is desired to use Analog Ramp symbol(s) to control this signal, then this signal should be tied together with the Level_Out output. In this way, one analog signal will control the light and always accurately reflect the current light level on the dimmer."

**Why it matters:** That truncated text was the entire reason we needed the SIMPL docs — it documents a mandatory SDK requirement (`TieInputToOutput`) that isn't mentioned anywhere in the S#Pro help. The bug we were fixing (level bounceback) was caused by not following this instruction.

**Expected behavior:** Show full signal descriptions, or provide `get_signal_detail(device, signal_name)` for the untruncated text of a specific signal.

## 4. Multi-product device pages

**What happened:**
```
get_device_signals("CLX-1DIM8")
→ "Device not found: CLX-1DIM8"

get_device_signals("CLX-2DIM8")
→ "Device not found in SIMPL Windows: CLX-2DIM8"
```

**What worked:** User knew to try `get_device_signals("CLX Dimming")` which found the shared "CLX Dimming Modules" page covering CLX-1DIM4, CLX-1DIM8, CLX-2DIM2, CLX-2DIM8, CLX-1DELV4, and CLX-1FLVC4 under one entry.

**Expected behavior:** When an individual model name isn't found, search for shared/family pages that list it as a covered model. Many Crestron product families use shared SIMPL pages (CLX Dimming Modules, GLPP power packs, etc.).

## 5. Slot-aware search

**What happened:**
```
search_signals("LevelIn CLX-2DIMU8", signal_type="analog_input")
→ "No signals found"

search_signals("Level_In CLX", signal_type="analog_input")
→ "No signals found"
```

**What worked:** `get_device_signals("CLX-2DIMU8 Dimmer Basic Controls")` — had to know the exact slot name.

**Why it failed:** CLX-2DIMU8's `LevelIn1-8` and `LevelOut1-8` signals are defined on the slot page "Slot-01: CLX-2DIMU8 Dimmer Basic Controls", not the main device page. `search_signals` doesn't index slot-level signals under the parent device.

**Expected behavior:** Index slot signals under the parent device name. When searching for "LevelIn" on "CLX-2DIMU8", the tool should find signals from all of its slots.

## 6. Signal → S#Pro reverse mapping

`cross_reference_member` goes S#Pro → SIMPL. The reverse (SIMPL signal `Level_In` on `CLW-DIMUEX-P` → S#Pro `DimmingLoad.Level`) would complete the loop. SIMPL docs often have better usage descriptions than S#Pro docs.

## 7. Compact output format

All tool responses (`inspect`, `search`, `get_class_info`, `cross_reference`) use decorative `======` separators, excessive blank lines, and padded headers that waste tokens. A compact format would convey the same information in a fraction of the context:

```
CLW-DIMUEX-P → ClwDimuEx (Crestron.SimplSharpPro.Lighting)
Signals:
  Level_In [analog_input → UShortInput]: Sets the light level. This signal should be tied together with the Level_Out output...
  Level_Out [analog_output → UShortOutput]: Reports the current level of the load when it changes...
```

vs current:

```
======================================================================
Cross-Reference: CLW-DIMUEX-P
SIMPL Windows -> SIMPL# Pro
======================================================================

S#Pro Class: ClwDimuEx Class
  Namespace: Crestron.SimplSharpPro.Lighting
  Path: html/2d0bfffd-3a33-9005-bbcc-f4dfff61771e.htm

Signal Type Mapping:
  SIMPL Windows             SIMPL# Pro               
  ───────────────────────── ─────────────────────────
  Digital input/output     BooleanInput/BooleanOutput
  ...
```

The signal type mapping table is static and the same for every device — include it once in the tool description, not every response.
