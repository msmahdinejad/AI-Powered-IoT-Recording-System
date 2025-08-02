import os
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from vosk import Model, KaldiRecognizer
import wave
import subprocess
import uuid 
import json

app = FastAPI()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Get model path from env or default
MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "models/vosk-model-small-en-us-0.15")
model = Model(MODEL_PATH)

def convert_to_wav(input_path, output_path):
    subprocess.run([
        "ffmpeg", "-i", input_path,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        output_path,
        "-y"
    ], check=True)

def transcribe(wav_path):
    wf = wave.open(wav_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    result_text = ""

    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            result_text += json.loads(rec.Result())['text'] + " "
    result_text += json.loads(rec.FinalResult())['text']
    return result_text.strip()

@app.post("/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):
    audio_id = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{audio_id}_{file.filename}")
    with open(input_path, "wb") as f:
        f.write(await file.read())

    wav_path = os.path.join(UPLOAD_DIR, f"{audio_id}.wav")
    try:
        convert_to_wav(input_path, wav_path)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Conversion failed: {e}"})

    try:
        text = transcribe(wav_path)
        txt_path = os.path.join(UPLOAD_DIR, f"{audio_id}.txt")
        with open(txt_path, "w") as f:
            f.write(text)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Transcription failed: {e}"})

    return {"id": audio_id, "transcription": text}

