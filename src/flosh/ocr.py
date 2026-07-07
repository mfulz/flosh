from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from flosh.capture import CaptureMode, capture_env, capture_raw_screenshot, render_output_path


@dataclass(frozen=True)
class OcrSettings:
    target_dir: Path
    mode: CaptureMode
    filename_template: str
    lang: str
    psm: int
    preprocess: bool
    keep_preprocessed: bool
    grimshot: str
    tesseract: str
    magick: str
    wl_copy: str


def capture_ocr_text(settings: OcrSettings) -> tuple[str, Path | None]:
    raw_path = capture_raw_screenshot(grimshot=settings.grimshot, mode=settings.mode)
    ocr_path = raw_path
    preprocessed_path: Path | None = None
    try:
        if settings.preprocess:
            preprocessed_path = preprocess_image(raw_path, magick=settings.magick)
            ocr_path = preprocessed_path
        text = run_tesseract(
            ocr_path,
            tesseract=settings.tesseract,
            lang=settings.lang,
            psm=settings.psm,
        )
        return text, preprocessed_path if settings.keep_preprocessed else None
    finally:
        raw_path.unlink(missing_ok=True)
        if preprocessed_path is not None and not settings.keep_preprocessed:
            preprocessed_path.unlink(missing_ok=True)


def preprocess_image(path: Path, *, magick: str) -> Path:
    with tempfile.NamedTemporaryFile(prefix="flosh-ocr-", suffix=".png", delete=False) as tmp:
        output = Path(tmp.name)
    proc = subprocess.run(
        [magick, str(path), "-colorspace", "Gray", "-normalize", str(output)],
        env=capture_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        output.unlink(missing_ok=True)
        details = (proc.stderr or "").strip()
        raise RuntimeError(f"OCR preprocessing failed: {details or magick}")
    return output


def run_tesseract(path: Path, *, tesseract: str, lang: str, psm: int) -> str:
    proc = subprocess.run(
        [tesseract, str(path), "stdout", "-l", lang, "--psm", str(psm)],
        env=capture_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        details = (proc.stderr or "").strip()
        raise RuntimeError(f"OCR failed: {details or tesseract}")
    return proc.stdout.rstrip("\n")


def copy_text_to_clipboard(text: str, *, wl_copy: str) -> None:
    proc = subprocess.run(
        [wl_copy, "--type", "text/plain"],
        input=text,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        details = (proc.stderr or "").strip()
        raise RuntimeError(f"clipboard copy failed: {details or wl_copy}")


def save_ocr_text(text: str, *, target_dir: Path, filename_template: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    output = render_output_path(target_dir, filename_template).with_suffix(".txt")
    if output.exists():
        stem = output.stem
        suffix = output.suffix
        for index in range(1, 1000):
            candidate = output.with_name(f"{stem}_{index}{suffix}")
            if not candidate.exists():
                output = candidate
                break
        else:
            raise RuntimeError(f"could not find free OCR text filename below: {target_dir}")
    output.write_text(text, encoding="utf-8")
    return output
