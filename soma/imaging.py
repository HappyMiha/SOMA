"""The world's painter: an image model on this PC's GPU paints an inhabitant in their scene,
as the inhabitant describes it.


stable-diffusion.cpp (Vulkan build) with SDXL-Lightning (4 steps) and the tiny
SDXL autoencoder runs locally from %LOCALAPPDATA%\\SOMA-imaging; measured on the
GTX 1060 6GB: about 4 GB of VRAM, 51 s of sampling at 1344×768 (the local
brain is unloaded first). Her widget shows the painting as pixel art, her
owner's choice after comparing it with figures drawn in code. Like the brain CLIs it is an inference
engine: it reads only the prompt she wrote and writes one image into a
temporary folder of SOMA's own; it never touches applications, files or
input. This is the second module allowed to start a process (contract test).
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path

WIDTH, HEIGHT = 1344, 768  # SDXL's own wide format, close to her widget's wide view
STEPS = 4
KEEP = (448, 256)  # what her memory keeps; her widget reduces it to its pixel grid (≤ 228 px wide)
# Her avatar is pixel art; the widget snaps the painting to its own grid and palette.
STYLE = "pixel art, 16-bit game scene"  # short: the prompt's start belongs to her
NEGATIVE = ("photo of a real person, celebrity, realistic human face, photorealistic, 3d render, text, letters, "
            "watermark, signature, nsfw, nudity, gore, deformed, blurry, low quality")


def imaging_root() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return local / "SOMA-imaging" if sys.platform == "win32" else Path.home() / ".local/share/soma-imaging"


class Imaging:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else imaging_root()
        self.last_seconds = None
        self.painting = False  # the GPU is the painter's right now (soma.health shows it)
        self._find()

    LOOK_AGAIN = 60  # seconds; live, right after a hard reset the painter was not found once and never again

    def _find(self):
        self._looked = time.monotonic()
        self.engine = self.model = self.vae = self.taesd = None
        try:
            self._look()
        except OSError:
            pass  # Not reachable right now: looked for again in a minute.

    def _look(self):
        names = ("sd-cli.exe", "sd.exe") if sys.platform == "win32" else ("sd-cli", "sd")
        engines = [path for name in names for path in sorted((self.root / "engine").rglob(name))] \
            if (self.root / "engine").exists() else []
        self.engine = engines[0] if engines else None
        models = self.root / "models"
        self.model = next(iter(sorted(models.glob("sdxl_lightning_4step*.safetensors"))), None) if models.exists() else None
        vae = models / "sdxl_vae.safetensors"
        self.vae = vae if vae.exists() else None
        # The tiny autoencoder decodes in about a second instead of 46 s of tiled
        # VAE on a GTX 1060; at her widget's 228 pixels the difference is invisible.
        tiny = models / "taesdxl" / "diffusion_pytorch_model.safetensors"
        self.taesd = tiny if tiny.exists() else None

    @property
    def available(self) -> bool:
        if not (self.engine and self.model) and time.monotonic() - self._looked >= self.LOOK_AGAIN:
            self._find()
        return bool(self.engine and self.model and self.engine.is_file() and self.model.is_file())

    def command(self, prompt: str, output: Path, seed: int) -> list[str]:
        # SDXL-Lightning: 4 Euler steps on the sgm_uniform ("trailing") schedule,
        # no classifier-free guidance. Weights quantized to q8_0 on load so the
        # model fits a 6 GB GPU; the VAE decodes in tiles.
        argv = [str(self.engine), "-m", str(self.model), "-p", STYLE + ", " + prompt, "-n", NEGATIVE,
                "--steps", str(STEPS), "--cfg-scale", "1.0", "--sampling-method", "euler",
                "--scheduler", "sgm_uniform", "--type", "q8_0", "--flash-attn", "auto",
                "-W", str(WIDTH), "-H", str(HEIGHT), "-s", str(seed), "-o", str(output)]
        if self.taesd:
            argv += ["--taesd", str(self.taesd)]
        else:
            argv += ["--vae-tiling"] + (["--vae", str(self.vae)] if self.vae else [])
        return argv

    def generate(self, prompt: str, seed: int, deadline: float, cancel=None) -> str:
        """A wide painting of her in her world, base64 JPEG; RuntimeError when the engine cannot paint."""
        if not self.available:
            raise RuntimeError("No image engine on this PC")
        started = time.monotonic()
        self.painting = True
        try:
            return self._paint(prompt, seed, deadline, cancel, started)
        finally:
            self.painting = False

    def _paint(self, prompt, seed, deadline, cancel, started) -> str:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with tempfile.TemporaryDirectory(prefix="soma-selfie-") as folder:
            output = Path(folder) / "selfie.png"
            process = subprocess.Popen(self.command(prompt, output, seed), cwd=folder, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            try:
                while process.poll() is None:
                    if time.monotonic() > deadline or (cancel is not None and cancel.is_set()):
                        process.kill()
                        process.wait(timeout=10)
                        raise RuntimeError("The selfie was not finished in time")
                    time.sleep(0.25)
            finally:
                if process.poll() is None:
                    process.kill()
            if process.returncode != 0 or not output.is_file():
                raise RuntimeError(f"The image engine stopped (code {process.returncode})")
            from PIL import Image
            with Image.open(output) as image:
                kept = image.convert("RGB").resize(KEEP, Image.Resampling.LANCZOS)
            buffer = BytesIO()
            kept.save(buffer, "JPEG", quality=90)  # ~40 KB in her append-only memory
        self.last_seconds = round(time.monotonic() - started, 1)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
