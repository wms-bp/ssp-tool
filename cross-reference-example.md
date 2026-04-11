## Cross-Referencing S#Pro and SIMPL Windows Documentation

The S#Pro SDK docs tell you *what* properties and events exist on a class, but often lack descriptions. The SIMPL Windows help has rich signal-level documentation — valid ranges, defaults, timing behavior, edge-trigger semantics — but uses different naming conventions and a completely different organizational structure.

Cross-referencing bridges the gap: start from either side and get the full picture.

### Example: CLW-DIMFLVEX-P Dimmer

**Starting from S#Pro** — you're writing a driver and inspect the class:

```
> inspect("ClwDimFlvExP")

ClwDimFlvExP Class
Namespace: Crestron.SimplSharpPro.Lighting
Signature: public sealed class ClwDimFlvExP : ClwDimexP

Properties:
  DimmingLoads         -> Collection of dimming loads for this device.
  ParameterRaiseLowerRate
  ParameterPresetFadeTime
  ParameterOffFadeTime
  DimmerRemoteButtonSettings
  ...
```

The SDK tells you `ParameterRaiseLowerRate` exists, but not what values it accepts or what it defaults to. The `DimmingLoads` collection has load objects with `LevelIn`, `FullOn`, `Raise`, `Lower` — but no description of the actual behavior.

**Cross-reference to SIMPL Windows** — one call fills in the gaps:

```
> cross_reference("ClwDimFlvExP")

CLW-DIMFLVEX-P → ClwDimFlvExP Class (Crestron.SimplSharpPro.Lighting)

Slot 01: Dimmer Controls
  Full_On    [D-In → BooleanInput]   Fades to max level using PresetFadeTime.
                                      Second rising edge during fade = soft cut (0.5s).
  Off        [D-In → BooleanInput]   Fades to 0% using OffFadeTime.
  Raise      [D-In → BooleanInput]   Level-sensitive: ramps to max while held high.
                                      Rate set by RaiseLowerRate parameter.
  Lower      [D-In → BooleanInput]   Level-sensitive: ramps to min while held high.
                                      Pauses 1s at min, then turns off if still held.
  Level_In   [A-In → UShortInput]    Sets level 0–100%. Full range accepted regardless
                                      of min/max. Tie to Level_Out for bidirectional tracking.
  Level_Out  [A-Out → UShortOutput]  Reports level on local/slave changes only —
                                      does NOT echo Level_In back.
  Load_Is_On [D-Out → BooleanOutput] High while load > 0%.

Slot 03: Dimmer Settings
  RaiseLowerRate       [Param]  1s–10s, default 3s
  PresetFadeTime       [Param]  0.25s–10s, default 1s
  OffFadeTime          [Param]  0.25s–30s, default 1s
  DimmerMinLevel       [Param]  0%–45%, default 0%
  DimmerMaxLevel       [Param]  55%–100%, default 100%
```

Now you know that `Raise` is level-sensitive (not edge-triggered), that `Lower` has a 1-second pause-then-off behavior at min level, that `Level_Out` doesn't echo `Level_In`, and that `RaiseLowerRate` accepts 1–10 seconds with a 3s default. None of this is in the S#Pro docs.

**Drill into a specific member** — when you need the full story on one property:

```
> cross_reference_member("ClwDimFlvExP", "LevelIn")

ClwDimFlvExP.LevelIn → Level_In [A-In → UShortInput]

  Sets the light level. Valid analog values range from 0% (Off) to 100%.
  The entire range of values is accepted regardless of the specified
  min/max levels. If it is desired to use Analog Ramp symbol(s) to
  control this signal, then this signal should be tied together with
  the Level_Out output. In this way, one analog signal will control
  the light and always accurately reflect the current light level.
```

### Why This Matters

| What you need | S#Pro alone | With cross-reference |
|---|---|---|
| Property exists? | Yes | Yes |
| C# type/signature? | Yes | Yes |
| Valid value ranges? | No | Yes (from SIMPL params) |
| Default values? | No | Yes |
| Edge vs. level trigger? | No | Yes |
| Timing/ramp behavior? | No | Yes |
| Signal interaction notes? | No | Yes (e.g., tie Level_In to Level_Out) |

The cross-reference tools handle the naming translation automatically — `LevelIn` ↔ `Level_In`, `ParameterRaiseLowerRate` ↔ `RaiseLowerRate`, `ClwDimFlvExP` ↔ `CLW-DIMFLVEX-P` — so you can start from whichever side you're working in.
