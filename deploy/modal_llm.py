"""Gemma 4 E4B — promed'dagi aynan o'sha GGUF fayl — Modal GPU'da: OpenAI'ga mos /v1/chat/completions, kalit bilan.

Ko'p xabarni tez o'qish kerak bo'lganda (eski tarixni yuklash, katta sinov to'plami): protsessorda bitta xabar ~30 s,
L4 da bir vaqtda 16 ta. Kundalik oqim promed'dagi konteynerda qoladi.

    modal secret create puls-llm-key LLM_KEY=<tasodifiy kalit>
    modal run deploy/modal_llm.py::fetch        # model faylini hajmga yuklaydi va sha256 ni qaytaradi
    modal deploy deploy/modal_llm.py            # manzil: https://<workspace>--puls-llm-serve.modal.run/v1
    modal app stop puls-llm                     # ish tugagach (bo'sh turganda baribir 2 daqiqada o'chadi)
"""
import subprocess

import modal

MODEL = "gemma-4-E4B-it-Q4_0.gguf"
URL = "https://huggingface.co/ggml-org/gemma-4-E4B-it-GGUF/resolve/main/" + MODEL
SLOTS = 16

vol = modal.Volume.from_name("puls-llm", create_if_missing=True)
image = modal.Image.from_registry("ghcr.io/ggml-org/llama.cpp:server-cuda", add_python="3.12").entrypoint([])
app = modal.App("puls-llm", image=image)


@app.function(volumes={"/models": vol}, timeout=1800)
def fetch() -> str:
    import hashlib
    import os
    import urllib.request

    path = "/models/" + MODEL
    if not os.path.exists(path):
        urllib.request.urlretrieve(URL, path + ".part")
        os.rename(path + ".part", path)
        vol.commit()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    print("sha256", h.hexdigest())
    return h.hexdigest()


@app.function(gpu=["L4", "A10G", "L40S", "T4"],  # L4 band bo'lsa keyingisi
              volumes={"/models": vol}, secrets=[modal.Secret.from_name("puls-llm-key")], scaledown_window=120,
              timeout=3600, max_containers=1)
@modal.concurrent(max_inputs=SLOTS * 2)
@modal.web_server(8080, startup_timeout=600)
def serve():
    import os

    subprocess.Popen(["/app/llama-server", "-m", "/models/" + MODEL, "-ngl", "99", "-c", str(SLOTS * 6144), "-np", str(SLOTS),
                      "--host", "0.0.0.0", "--port", "8080", "--jinja", "--api-key", os.environ["LLM_KEY"]])
