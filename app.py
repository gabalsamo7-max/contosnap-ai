import streamlit as st
import pandas as pd
import io
import time
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

st.set_page_config(page_title="Doc2Excel AI - Contabilità Automatica", page_icon="📊", layout="wide")

# --- CONFIGURAZIONE COMMERCIALE ---
CODICI_PRO_VALIDI = ["VIP2026", "CLIENTEPRO", "STUDIO100"] # Codici da dare a chi paga su Stripe
LIMITE_GRATIS = 2 # Numero massimo di file elaborabili gratuitamente
LINK_PAGAMENTO_STRIPE = "https://stripe.com" # Da sostituire con il tuo link Stripe

# Recupera la API Key dal file segreto (.streamlit/secrets.toml)
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    API_KEY = ""

# --- INTESTAZIONE E LANDING PAGE ---
st.title("📊 Doc2Excel AI — Trasforma Fatture e Scontrini in Excel in 5 secondi")
st.markdown("Basta copiare dati a mano. Carica **PDF digitali, scansioni o foto di scontrini/bolle** e scarica subito il foglio Excel pronto per il commercialista.")

# --- BARRA LATERALE: PIANO GRATUITO VS PRO ---
with st.sidebar:
    st.header("💎 Piano Attivo")
    codice_inserito = st.text_input("Hai un Codice Licenza PRO?", type="password", placeholder="Inserisci codice...")
    
    utente_pro = codice_inserito.strip().upper() in CODICI_PRO_VALIDI
    
    if utente_pro:
        st.success("✅ **PIANO PRO ATTIVO**\nElaborazione massiva illimitata sbloccata!")
    else:
        st.info(f"🆓 **PIANO GRATUITO**\nPuoi elaborare fino a **{LIMITE_GRATIS} documenti** per volta.")
        st.markdown("### Passa a PRO (15€/mese)")
        st.markdown("- ✅ Caricamento massivo illimitato\n- ✅ Supporto foto, scansioni e PDF\n- ✅ Categorizzazione automatica")
        st.link_button("💳 Ottieni Codice PRO", LINK_PAGAMENTO_STRIPE, use_container_width=True)

# --- STRUTTURA DATI EXCEL ---
class DatiFattura(BaseModel):
    fornitore: str = Field(description="Ragione sociale o nome dell'azienda/negozio che ha emesso il documento")
    partita_iva: str = Field(description="Partita IVA o Codice Fiscale del fornitore")
    numero_documento: str = Field(description="Numero della fattura, bolla, scontrino o ricevuta")
    data_documento: str = Field(description="Data di emissione in formato GG/MM/AAAA")
    imponibile: float = Field(description="Importo imponibile netto (senza IVA), usa 0.0 se non presente")
    iva: float = Field(description="Importo dell'IVA, usa 0.0 se non presente")
    totale: float = Field(description="Importo totale finale pagato o da pagare")
    categoria: str = Field(description="Categoria della spesa (es. Ristorazione, Utenze, Materiali, Carburante, Servizi, Altro)")

def estrai_da_documento_multimodale(file_bytes, mime_type, chiave_api):
    client = genai.Client(api_key=chiave_api)
    
    prompt = """
    Analizza visivamente questo documento (può essere un PDF digitale, una scansione o la foto di uno scontrino/fattura/bolla).
    Leggi con attenzione tutti i testi e i numeri presenti nell'immagine o nel PDF ed estrai i dati richiesti.
    Se un dato non è leggibile o non è presente, inserisci 'N/D' per i testi o 0.0 per i numeri.
    """
    
    documento_allegato = types.Part.from_bytes(
        data=file_bytes,
        mime_type=mime_type,
    )
    
    modelli_da_provare = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"]
    ultimo_errore = None
    
    for modello in modelli_da_provare:
        for tentativo in range(2):
            try:
                response = client.models.generate_content(
                    model=modello,
                    contents=[documento_allegato, prompt],
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": DatiFattura,
                    },
                )
                return response.parsed
            except Exception as e:
                ultimo_errore = e
                if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                    time.sleep(2)
                else:
                    raise e
    raise ultimo_errore

# --- AREA DI CARICAMENTO ---
uploaded_files = st.file_uploader(
    "Trascina qui PDF, scansioni o foto di scontrini/fatture",
    type=["pdf", "jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

if uploaded_files:
    if not API_KEY:
        st.error("⚠️ Servizio momentaneamente non configurato (manca il file .streamlit/secrets.toml).")
    elif not utente_pro and len(uploaded_files) > LIMITE_GRATIS:
        st.warning(f"⚠️ Hai caricato **{len(uploaded_files)} file**, ma il Piano Gratuito permette massimo **{LIMITE_GRATIS} file** alla volta. Rimuovi i file in eccesso oppure inserisci un **Codice Licenza PRO** nella barra a sinistra!")
    else:
        if st.button("🚀 Trasforma in Excel", type="primary"):
            risultati = []
            barra_progresso = st.progress(0)
            
            for indice, file in enumerate(uploaded_files):
                try:
                    dati = estrai_da_documento_multimodale(file.getvalue(), file.type, API_KEY)
                    risultati.append({
                        "File": file.name,
                        "Fornitore": dati.fornitore,
                        "Partita IVA": dati.partita_iva,
                        "N. Documento": dati.numero_documento,
                        "Data": dati.data_documento,
                        "Imponibile (€)": dati.imponibile,
                        "IVA (€)": dati.iva,
                        "Totale (€)": dati.totale,
                        "Categoria": dati.categoria
                    })
                except Exception as e:
                    st.error(f"Errore su {file.name}: {e}")
                
                barra_progresso.progress((indice + 1) / len(uploaded_files))
            
            if risultati:
                df = pd.DataFrame(risultati)
                st.success(f"✅ Elaborati con successo {len(risultati)} documenti!")
                
                st.subheader("Anteprima dati (clicca sulle celle per eventuali correzioni)")
                df_modificato = st.data_editor(df, use_container_width=True)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_modificato.to_excel(writer, index=False, sheet_name='Contabilita')
                
                st.download_button(
                    label="📥 Scarica File Excel (.xlsx)",
                    data=buffer.getvalue(),
                    file_name="contabilita_estratta.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )




