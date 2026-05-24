"""NURA Video Assembler v2 — FFmpeg subprocess backend.

CapCut-level quality: transitions (xfade), easing (cubic-bezier),
color grading, GPU encode (NVENC auto-detect)."""

import re
import subprocess
from pathlib import Path
from typing import Literal

import imageio_ffmpeg
from pydantic import BaseModel

FPS = 24
NURA_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_DEFAULT_FONT = None
for _fp in [
    "C\\:/Windows/Fonts/arial.ttf",
    "C\\:/Windows/Fonts/calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]:
    if Path(_fp.replace("\\:", ":")).exists():
        _DEFAULT_FONT = _fp
        break
_FFMPEG = Path(imageio_ffmpeg.get_ffmpeg_exe())


# ──────────────────────────────────────────────
#  Easing
# ──────────────────────────────────────────────

def _ease_fn(kind: str) -> str:
    if kind == "cubic-in-out":
        return "if(lte(t,0.5),4*pow(t,3),1-pow(-2*t+2,3)/2)"
    if kind == "cubic-out":
        return "1-pow(1-t,3)"
    if kind == "cubic-in":
        return "pow(t,3)"
    return "t"


# ──────────────────────────────────────────────
#  Pydantic models (backward compatible)
# ──────────────────────────────────────────────

class Transition(BaseModel):
    type: str = "dissolve"
    duration: float = 0.5


class ColorGrading(BaseModel):
    enabled: bool = False
    shadows_red: float = 0.0
    shadows_green: float = 0.0
    shadows_blue: float = 0.0
    midtones_red: float = 0.0
    midtones_green: float = 0.0
    midtones_blue: float = 0.0
    highlights_red: float = 0.0
    highlights_green: float = 0.0
    highlights_blue: float = 0.0
    glow: bool = False
    glow_radius: int = 15
    glow_opacity: float = 0.2


class TextOverlay(BaseModel):
    type: Literal["text"] = "text"
    text: str
    start: float = 0.0
    end: float | None = None
    x: float | str = 0
    y: float | str = -0.3
    font_size: int = 24
    color: str = "#FF6B00"
    font: str | None = None
    border_color: str = "#000000"
    border_width: int = 4
    letter_spacing: int = 0


class VideoOverlay(BaseModel):
    type: Literal["video"] = "video"
    src: str
    start: float = 0.0
    end: float | None = None
    x: float | str = 0.5
    y: float | str = 0
    width: float | int = 0.4
    height: float | int | None = None
    color_grading: ColorGrading = ColorGrading()


class ImageOverlay(BaseModel):
    type: Literal["image"] = "image"
    src: str
    start: float = 0.0
    end: float | None = None
    x: float | str = 0
    y: float | str = 0
    width: float | int | None = None
    height: float | int | None = None


class ZoomEffect(BaseModel):
    type: Literal["zoom"] = "zoom"
    start: float = 0.0
    duration: float = 2.0
    from_scale: float = 1.0
    to_scale: float = 1.3
    easing: str = "cubic-in-out"


Overlay = TextOverlay | VideoOverlay | ImageOverlay | ZoomEffect


class Scene(BaseModel):
    source: str | None = None
    source_keywords: list[str] = []
    start: float = 0.0
    duration: float
    transition: Transition | None = None
    nura_text: str | None = None
    overlays: list[Overlay] = []
    color_grading: ColorGrading = ColorGrading()


class SubtitlesConfig(BaseModel):
    enabled: bool = True
    mode: Literal["auto", "manual"] = "manual"
    font_size: int = 50
    color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: float = 3.0
    y_position: float = 0.7


class ScenarioConfig(BaseModel):
    name: str = "nura_video"
    format_type: str = "type1"
    nura_video: str
    scenes: list[Scene]
    subtitles: SubtitlesConfig = SubtitlesConfig()


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _resolve(p: str) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else NURA_ROOT / pp


def _fmt_time(secs: float) -> str:
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    ms = int((secs - int(secs)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _probe_video(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        [str(_FFMPEG), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # Match actual dimensions (not hex codec tags like 0x...)
    m = re.search(r"Stream.*Video.*[, ](\d+)x(\d+)[,\s\]]", r.stderr)
    if not m:
        raise RuntimeError(f"Could not probe video: {path}")
    return int(m.group(1)), int(m.group(2))


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        [str(_FFMPEG), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)[.,](\d+)", r.stderr)
    if not m:
        raise RuntimeError(f"Could not probe duration: {path}")
    return (
        int(m.group(1)) * 3600
        + int(m.group(2)) * 60
        + int(m.group(3))
        + int(m.group(4)) / (10 ** len(m.group(4)))
    )


def _has_audio(path: Path) -> bool:
    r = subprocess.run(
        [str(_FFMPEG), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "Audio:" in r.stderr


def _has_gpu() -> bool:
    r = subprocess.run(
        [str(_FFMPEG), "-hide_banner", "-encoders"],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "hevc_nvenc" in r.stdout


def _pos_px(v: float | str, size: int) -> str:
    if isinstance(v, str):
        return v
    if 0 <= v <= 1:
        return str(int(v * size))
    return str(int(v))


TEXT_FIXES = {
    "на некоторые вещи никогда не меняются.": "Но некоторые вещи никогда не меняются.",
    "Меня называют Нура.": "Меня зовут Нура.",
    "в звездах,": "в звёздах,",
}


def _fix_srt(srt: str) -> str:
    """Apply known transcription error fixes."""
    for old, new in TEXT_FIXES.items():
        srt = srt.replace(old, new)
    return srt


def _esc(v: str) -> str:
    """Escape for FFmpeg filter_complex string value."""
    return (v.replace("\\", "\\\\")
             .replace("'", "'\\''")
             .replace(":", "\\:")
             .replace("=", "\\=")
             .replace("[", "\\[")
             .replace("]", "\\]"))


def _ffpath(p: Path) -> str:
    """Convert path to FFmpeg-compatible string (forward slashes)."""
    return str(p).replace("\\", "/")


def _ffpath_filter(p: Path) -> str:
    """Path for use in filter_complex params (escape colons for drive letter)."""
    return str(p).replace("\\", "/").replace(":", "\\:")


# ──────────────────────────────────────────────
#  Zoom expression builder
# ──────────────────────────────────────────────

def _zoom_z_expr(zo: ZoomEffect, dur: float) -> str:
    fps = FPS
    z0 = int(zo.start * fps)
    z1 = int((zo.start + zo.duration) * fps)
    zd = z1 - z0
    if zd <= 0 or abs(zo.to_scale - zo.from_scale) < 0.001:
        return ""

    t_sub = f"(on-{z0})/{zd}"
    ease = re.sub(r'\bt\b', f"({t_sub})", _ease_fn(zo.easing))
    rng = zo.to_scale - zo.from_scale
    return (f"if(lt(on,{z0}),{zo.from_scale},"
            f"if(gt(on,{z1}),{zo.to_scale},"
            f"{zo.from_scale}+{rng}*({ease})))")


# ──────────────────────────────────────────────
#  SRT generation (transition-adjusted)
# ──────────────────────────────────────────────

def _srt_lines(scenes: list[Scene]) -> str:
    lines: list[str] = []
    idx = 1
    off = 0.0
    for si, sc in enumerate(scenes):
        if not sc.nura_text:
            continue
        words = sc.nura_text.split()
        if not words:
            continue
        dur = sc.duration if sc.duration > 0 else 3.0
        n = max(1, round(dur / 3))
        cs = max(1, len(words) // n)
        chunks = [words[i:i + cs] for i in range(0, len(words), cs)]
        cd = dur / len(chunks)
        t = sc.start - off
        for chunk in chunks:
            te = t + cd
            lines.append(str(idx))
            lines.append(f"{_fmt_time(t)} --> {_fmt_time(te)}")
            lines.append(" ".join(chunk))
            lines.append("")
            t = te
            idx += 1
        if si < len(scenes) - 1 and scenes[si + 1].transition:
            off += scenes[si + 1].transition.duration
    return "\n".join(lines)


def _auto_srt(path: Path) -> str | None:
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(str(path), language="ru")
        lines: list[str] = []
        for i, s in enumerate(segs):
            lines.append(str(i + 1))
            lines.append(f"{_fmt_time(s.start)} --> {_fmt_time(s.end)}")
            lines.append(s.text.strip())
            lines.append("")
        return "\n".join(lines) if lines else None
    except ImportError:
        return None


def make_srt(cfg: ScenarioConfig, path: Path) -> str:
    if cfg.subtitles.mode == "auto":
        s = _auto_srt(path)
        if s:
            return s
    return _srt_lines(cfg.scenes)


# ──────────────────────────────────────────────
#  Assemble
# ──────────────────────────────────────────────

def assemble(cfg: ScenarioConfig) -> Path:
    vp = _resolve(cfg.nura_video)
    if not vp.exists():
        raise FileNotFoundError(f"Video not found: {vp}")

    out_dir = NURA_ROOT / "videos" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{cfg.name}.mp4"

    W, H = _probe_video(vp)
    total_dur = _probe_duration(vp)
    print(f"[1/6] Video: {vp.name} ({W}x{H}, {total_dur:.1f}s)")

    # ── subtitles ──
    srt_path = None
    if cfg.subtitles.enabled:
        print("[2/6] Generating subtitles...")
        srt = _fix_srt(make_srt(cfg, vp))
        srt_path = out_dir / f"{cfg.name}_subtitles.srt"
        srt_path.write_text(srt, encoding="utf-8")

    # ── collect overlay video files for extra inputs ──
    extra_inputs: list[Path] = []
    extra_path_set: set[str] = set()
    for sc in cfg.scenes:
        for ov in sc.overlays:
            if ov.type == "video":
                p = _resolve(ov.src)
                if p.exists() and str(p) not in extra_path_set:
                    extra_inputs.append(p)
                    extra_path_set.add(str(p))

    # ── collect scene-level source files (full-screen stock) ──
    scene_sources: dict[str, int] = {}
    scene_source_info: dict[int, Path] = {}
    for sc in cfg.scenes:
        if sc.source:
            sp = str(_resolve(sc.source))
            if sp not in scene_sources:
                idx = len(scene_sources) + 1
                scene_sources[sp] = idx
                scene_source_info[idx] = _resolve(sc.source)

    # ── build filter_complex ──
    n_extra = len(extra_inputs) + len(scene_source_info)
    print(f"[3/6] Building filter graph ({len(cfg.scenes)} scene(s), "
          f"{n_extra} extra input(s))...")

    parts: list[str] = []
    label_ctr = 0

    has_audio = _has_audio(vp)

    def _nl(kind: str = "v") -> str:
        nonlocal label_ctr
        lbl = f"[n{label_ctr}{kind}]"
        label_ctr += 1
        return lbl

    scene_v_labels: list[str] = []
    scene_a_labels: list[str] = []

    # silence source for audio-less inputs
    if not has_audio:
        silence_tag = _nl("s")
        parts.append(
            f"aevalsrc=0:d={total_dur}:s=44100{silence_tag}"
        )

    for si, sc in enumerate(cfg.scenes):
        if sc.source:
            src_idx = scene_sources[str(_resolve(sc.source))]
            input_v_tag = f"[{src_idx}:v]"
            input_a_tag = f"[{src_idx}:a]"
            src_total = _probe_duration(_resolve(sc.source))
        else:
            input_v_tag = "[0:v]"
            input_a_tag = silence_tag if not has_audio else "[0:a]"
            src_total = total_dur

        sd = sc.duration if sc.duration > 0 else (src_total - sc.start)
        parts_v: list[str] = []

        # trim
        parts_v.append(
            f"{input_v_tag}trim=start={sc.start}:duration={sd},"
            f"setpts=PTS-STARTPTS,fps=fps={FPS}{_nl('v')}"
        )
        parts_v.append(
            f"{input_a_tag}atrim=start={sc.start}:duration={sd},"
            f"asetpts=PTS-STARTPTS{_nl('a')}"
        )
        cv = f"[n{label_ctr - 2}v]"
        ca = f"[n{label_ctr - 1}a]"

        # scale full-screen stock scenes to main resolution
        if sc.source:
            scale_lbl = _nl('v')
            parts_v.append(
                f"{cv}scale=width={W}:height={H}:force_original_aspect_ratio=1,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black{scale_lbl}"
            )
            cv = scale_lbl

        # zoom
        for ov in sc.overlays:
            if ov.type == "zoom" and ov.duration > 0 and abs(ov.to_scale - ov.from_scale) > 0.001:
                zexpr = _zoom_z_expr(ov, sd)
                if zexpr:
                    parts_v.append(
                        f"{cv}zoompan=z='{zexpr}':d=1:s={W}x{H}:fps={FPS}:"
                        f"x=iw/2-(iw/zoom/2):y=ih/2-(ih/zoom/2){_nl('v')}"
                    )
                    cv = f"[n{label_ctr - 1}v]"

        # text overlays
        for ov in sc.overlays:
            if ov.type != "text":
                continue
            px = _pos_px(ov.x, W)
            py = _pos_px(ov.y, H)
            c = ov.color.lstrip("#")
            bc = ov.border_color.lstrip("#")
            bw = ov.border_width
            s = ov.start
            e = ov.end if ov.end is not None else sd
            if e <= s:
                continue
            txt = _esc(ov.text)
            ff = ov.font or _DEFAULT_FONT
            ff_arg = f"fontfile='{ff}':" if ff else ""
            parts_v.append(
                f"{cv}drawtext={ff_arg}text='{txt}':fontsize={ov.font_size}:"
                f"fontcolor=0x{c}:bordercolor=0x{bc}:borderw={bw}:"
                f"x={px}:y={py}:"
                f"enable='between(t,{s},{e})'{_nl('v')}"
            )
            cv = f"[n{label_ctr - 1}v]"

        # video PiP overlays (using movie source to avoid multi-input complexity)
        for ov in sc.overlays:
            if ov.type != "video":
                continue
            ovp = _resolve(ov.src)
            if not ovp.exists():
                print(f"  Warning: video not found: {ov.src}")
                continue
            od = (ov.end if ov.end is not None else sd) - ov.start
            if od <= 0:
                continue
            ow = ov.width if isinstance(ov.width, int) else int(ov.width * W)
            px = _pos_px(ov.x, W)
            py = _pos_px(ov.y, H)

            # scale overlay
            overlay_label = _nl('o')
            parts_v.append(
                f"movie='{_ffpath_filter(ovp)}'[mv_{si}_{ov.start}];"
                f"[mv_{si}_{ov.start}]trim=duration={od},setpts=PTS-STARTPTS,"
                f"scale=width={ow}:height=-2,setpts=PTS+{ov.start}/TB{overlay_label}"
            )

            # apply color grading to overlay before compositing
            cg = ov.color_grading
            if cg.enabled:
                has_cb = any(getattr(cg, f) != 0.0 for f in
                       ["shadows_red", "shadows_green", "shadows_blue",
                        "midtones_red", "midtones_green", "midtones_blue",
                        "highlights_red", "highlights_green", "highlights_blue"])
                if has_cb:
                    cg_label = _nl('c')
                    parts_v.append(
                        f"{overlay_label}colorbalance="
                        f"rs={cg.shadows_red}:gs={cg.shadows_green}:bs={cg.shadows_blue}:"
                        f"rm={cg.midtones_red}:gm={cg.midtones_green}:bm={cg.midtones_blue}:"
                        f"rh={cg.highlights_red}:gh={cg.highlights_green}:bh={cg.highlights_blue}"
                        f"{cg_label}"
                    )
                    overlay_label = cg_label
                if cg.glow:
                    s0 = _nl('s')
                    s1 = _nl('s')
                    b0 = _nl('b')
                    parts_v.append(f"{overlay_label}split=2{s0}{s1}")
                    parts_v.append(f"{s0}gblur=sigma={cg.glow_radius}{b0}")
                    g_label = _nl('g')
                    parts_v.append(f"{s1}{b0}blend=all_mode=screen:all_opacity={cg.glow_opacity}{g_label}")
                    overlay_label = g_label

            # composite onto main scene
            ov_target = _nl('v')
            parts_v.append(
                f"{cv}{overlay_label}overlay=x={px}:y={py}:"
                f"enable='between(t,{ov.start},{ov.end or sd})'{ov_target}"
            )
            cv = ov_target

        # image overlays (movie source)
        for ov in sc.overlays:
            if ov.type != "image":
                continue
            ip = _resolve(ov.src)
            if not ip.exists():
                print(f"  Warning: image not found: {ov.src}")
                continue
            iid = (ov.end if ov.end is not None else sd) - ov.start
            if iid <= 0:
                continue
            ow = ov.width if isinstance(ov.width, int) else int(ov.width * W)
            px = _pos_px(ov.x, W)
            py = _pos_px(ov.y, H)
            parts_v.append(
                f"movie='{_ffpath_filter(ip)}'[im_{si}_{ov.start}];"
                f"[im_{si}_{ov.start}]trim=duration={iid},setpts=PTS-STARTPTS,"
                f"scale=width={ow}:height=-2,setpts=PTS+{ov.start}/TB{_nl('i')};"
                f"{cv}[n{label_ctr - 1}i]overlay=x={px}:y={py}:"
                f"enable='between(t,{ov.start},{ov.end or sd})'{_nl('v')}"
            )
            cv = f"[n{label_ctr - 1}v]"

        # ── color grading ──
        cg = sc.color_grading
        if cg.enabled:
            has_cb = any(getattr(cg, f) != 0.0 for f in
                   ["shadows_red", "shadows_green", "shadows_blue",
                    "midtones_red", "midtones_green", "midtones_blue",
                    "highlights_red", "highlights_green", "highlights_blue"])
            if has_cb:
                parts_v.append(
                    f"{cv}colorbalance="
                    f"rs={cg.shadows_red}:gs={cg.shadows_green}:bs={cg.shadows_blue}:"
                    f"rm={cg.midtones_red}:gm={cg.midtones_green}:bm={cg.midtones_blue}:"
                    f"rh={cg.highlights_red}:gh={cg.highlights_green}:bh={cg.highlights_blue}"
                    f"{_nl('v')}"
                )
                cv = f"[n{label_ctr - 1}v]"
            if cg.glow:
                s0 = f"[n{label_ctr}s]"
                s1 = f"[n{label_ctr + 1}s]"
                b0 = f"[n{label_ctr}b]"
                parts_v.append(f"{cv}split=2{s0}{s1}")
                parts_v.append(f"{s0}gblur=sigma={cg.glow_radius}{b0}")
                label_ctr += 2
                parts_v.append(f"{s1}{b0}blend=all_mode=screen:all_opacity={cg.glow_opacity}{_nl('v')}")
                cv = f"[n{label_ctr - 1}v]"

        scene_v_labels.append(cv)
        scene_a_labels.append(ca)
        parts.extend(parts_v)

    # ── chain transitions via xfade ──
    print("[4/6] Chaining transitions...")

    if len(scene_v_labels) == 1:
        fv, fa = scene_v_labels[0], scene_a_labels[0]
    else:
        cur = cfg.scenes[0].duration
        tr1 = cfg.scenes[1].transition
        td1 = tr1.duration if tr1 else 0.5
        tt1 = tr1.type if tr1 else "dissolve"
        off1 = cur - td1
        xl = _nl("f")
        xla = _nl("af")
        parts.append(
            f"{scene_v_labels[0]}{scene_v_labels[1]}"
            f"xfade=transition={tt1}:duration={td1}:offset={off1}{xl}"
        )
        parts.append(
            f"{scene_a_labels[0]}{scene_a_labels[1]}"
            f"acrossfade=d={td1}{xla}"
        )
        cur = cur + cfg.scenes[1].duration - td1
        pv, pa = xl, xla

        for i in range(2, len(scene_v_labels)):
            tr = cfg.scenes[i].transition
            td = tr.duration if tr else 0.5
            tt = tr.type if tr else "dissolve"
            off = cur - td
            xl = _nl("f")
            xla = _nl("af")
            parts.append(
                f"{pv}{scene_v_labels[i]}"
                f"xfade=transition={tt}:duration={td}:offset={off}{xl}"
            )
            parts.append(
                f"{pa}{scene_a_labels[i]}"
                f"acrossfade=d={td}{xla}"
            )
            cur = cur + cfg.scenes[i].duration - td
            pv, pa = xl, xla

        fv, fa = pv, pa

    # ── subtitles overlay ──
    if srt_path:
        sl = _nl("s")
        margin_v = int(H * (1 - cfg.subtitles.y_position))
        parts.append(
            f"{fv}subtitles='{_ffpath_filter(srt_path)}':"
            f"original_size={W}x{H}:"
            f"force_style='Alignment=2,MarginV={margin_v}'{sl}"
        )
        fv = sl

    # ── encode ──
    gpu = _has_gpu()
    if gpu:
        # Verify CUDA runtime is actually loadable
        test = subprocess.run(
            [str(_FFMPEG), "-f", "null", "-v", "quiet",
             "-init_hw_device", "cuda=test:0", "-hwaccel", "cuda"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if test.returncode != 0:
            gpu = False

    print(f"[5/6] Encoder: {'GPU (HEVC NVENC)' if gpu else 'CPU (libx264)'}")

    filter_str = ";".join(parts)
    cmd = [
        str(_FFMPEG), "-y", "-hide_banner",
        "-i", str(vp),
    ]
    for idx in sorted(scene_source_info):
        cmd += ["-i", str(scene_source_info[idx])]
    cmd += [
        "-filter_complex", filter_str,
        "-map", fv,
        "-map", fa,
    ]

    if gpu:
        cmd += ["-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr",
                "-cq", "23", "-b:v", "5M", "-maxrate", "10M",
                "-pix_fmt", "p010le", "-c:a", "aac", "-movflags", "+faststart"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"]

    cmd.append(str(out_path))

    print(f"[6/6] Rendering -> {out_path.name}...")
    print(f"  filter graph: {len(parts)} nodes")

    r = subprocess.run(cmd, capture_output=True, text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        print("--- FFmpeg stderr (last 3K) ---")
        print(r.stderr[-3000:])
        print("---")
        raise RuntimeError(f"FFmpeg failed (code {r.returncode})")
    
    # DEBUG: print lines with subtitle/ass/libtass
    for line in r.stderr.splitlines():
        if any(kw in line.lower() for kw in ['subtitle', 'libass', 'font', 'style']):
            print("  [ff]", line)

    print(f"\nDone: {out_path}")
    return out_path
