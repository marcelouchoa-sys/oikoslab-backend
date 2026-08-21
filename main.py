# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import islmbp, exemplos_didaticos, modelo_proprio, economia_real, simulador_dinamico

app = FastAPI(title="OikosLab API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://oikoslab-platform.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(islmbp.router,        prefix="/islmbp",        tags=["IS-LM-BP"])
app.include_router(exemplos_didaticos.router, prefix="/exemplos-didaticos", tags=["Exemplos Didaticos"])
app.include_router(modelo_proprio.router, prefix="/modelo",       tags=["Modelo Proprio"])
app.include_router(economia_real.router,      prefix="/economia-real",    tags=["Economia Real"])
app.include_router(simulador_dinamico.router, prefix="/simulador-dinamico", tags=["Simulador Dinamico"])

@app.get("/")
def root():
    return {"status": "ok", "projeto": "OikosLab API v2"}